#!/usr/bin/env python3
"""
Whale Watch — Bot de signaux BTC basé sur les mouvements de wallets whales.

Stratégie (issue de l'analyse on-chain) :
  - Wallet 1 (H8BgJ..., Solana)  : ~687M USDC en réserve. Ses dépôts USDC vers
    Binance quand BTC < 90k$ ont historiquement précédé des hausses de +5 à +16%.
  - Wallet 2 (9WzDX..., Solana)  : whale SOL massif, même compte Binance cible.
    Une recharge (Binance -> wallet) a marqué un creux de marché (fév 2026).
  - Wallet 3 (0xF977..., Ethereum) : Binance Hot Wallet 20. Les gros reshuffles
    internes à BTC < 92k$ ont précédé les plus fortes hausses (+15 à +24%).

Sécurité :
  - Aucune dépendance externe (stdlib uniquement) -> pas de risque supply-chain.
  - Le bot ne fait qu'ENVOYER des messages Telegram (sortant HTTPS).
    Il n'écoute aucun webhook, ne lit aucune commande -> surface d'attaque nulle.
  - Le token n'est jamais loggé ni écrit sur disque.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# La console Windows (cp1252) ne sait pas afficher les emojis en local
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

SOLANA_RPCS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-rpc.publicnode.com",
]
ETH_RPCS = [
    "https://ethereum-rpc.publicnode.com",
    "https://eth.llamarpc.com",
]

WHALE_1 = "H8BgJgae6qhMtf7BM2JtddywSQt11WdxHHxkGLNX5hss"
WHALE_2 = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
BINANCE_SOL = "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"
WHALE_LABELS = {WHALE_1: "Wallet 1 (H8BgJ…5hss)", WHALE_2: "Wallet 2 (9WzDX…AWWM)"}

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
MINT_NAMES = {USDC_MINT: "USDC", USDT_MINT: "USDT"}

BINANCE_HW20 = "0xf977814e90da44bfa03b6295a0616a897441acec"
USDT_ETH = "0xdac17f958d2ee523a2206206994597c13d831ec7"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

MIN_SOL_TRANSFER = 10_000_000     # $ — seuil d'alerte transferts whales Solana
MIN_ETH_TRANSFER = 150_000_000    # $ — seuil d'alerte mouvements Binance HW20
HEARTBEAT_SECS = 7 * 86400        # 1 message de vie par semaine
MAX_TX_PER_ACCOUNT = 10           # limite de tx analysées par compte et par run

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

DRY_RUN = "--dry-run" in sys.argv

# ----------------------------------------------------------------------------
# HTTP / RPC
# ----------------------------------------------------------------------------


def http_json(url, payload=None, timeout=25):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "whale-watch/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def rpc_call(endpoints, method, params):
    """Appel JSON-RPC avec bascule automatique sur le endpoint de secours."""
    last_err = None
    for url in endpoints:
        for attempt in range(2):
            try:
                out = http_json(url, {"jsonrpc": "2.0", "id": 1,
                                      "method": method, "params": params})
                if "error" in out:
                    raise RuntimeError(f"RPC error: {out['error'].get('message')}")
                return out.get("result")
            except Exception as e:  # réseau, rate-limit, etc.
                last_err = e
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{method} a échoué sur tous les endpoints: {last_err}")


def sol_rpc(method, params):
    time.sleep(0.4)  # rester poli avec les RPC publics
    return rpc_call(SOLANA_RPCS, method, params)


def eth_rpc(method, params):
    time.sleep(0.3)
    return rpc_call(ETH_RPCS, method, params)


# ----------------------------------------------------------------------------
# Telegram (sortant uniquement)
# ----------------------------------------------------------------------------


def send_telegram(text):
    if DRY_RUN:
        print("---- MESSAGE (dry-run) ----")
        print(text)
        print("---------------------------")
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("ERREUR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID manquants.")
        sys.exit(1)
    try:
        http_json(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    except urllib.error.HTTPError as e:
        # Ne jamais afficher l'URL (elle contient le token).
        print(f"ERREUR Telegram: HTTP {e.code}")
        sys.exit(1)


# ----------------------------------------------------------------------------
# Prix BTC
# ----------------------------------------------------------------------------


def btc_price():
    try:
        out = http_json(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        )
        return float(out["bitcoin"]["usd"])
    except Exception:
        pass
    try:
        out = http_json("https://api.coinbase.com/v2/prices/BTC-USD/spot")
        return float(out["data"]["amount"])
    except Exception:
        return None


def classify_signal(price):
    """Règles issues de l'analyse historique des 3 wallets."""
    if price is None:
        return "⚪️ Prix BTC indisponible — signal non classifié", None
    if price < 90_000:
        return (
            "🟢 <b>SIGNAL D'ACHAT FORT</b>\n"
            "Historique : dépôt whale + BTC &lt; 90k$ a précédé des hausses de "
            "+5% à +16% en 2 à 4 semaines (tous les cas observés).",
            (price * 1.05, price * 1.16),
        )
    if price < 100_000:
        return (
            "🟡 <b>Signal modéré</b> — zone intermédiaire 90-100k$, "
            "résultats historiques mixtes.",
            None,
        )
    return (
        "🔴 <b>PRUDENCE</b> — au-dessus de 100k$, les dépôts whales ont "
        "historiquement précédé des baisses (-8% à -27%). "
        "Possible distribution, pas accumulation.",
        None,
    )


def fmt_usd(x):
    return f"{x:,.0f}".replace(",", " ")


# ----------------------------------------------------------------------------
# Surveillance Solana (wallets 1 & 2)
# ----------------------------------------------------------------------------


def token_accounts(owner, mint):
    res = sol_rpc(
        "getTokenAccountsByOwner",
        [owner, {"mint": mint}, {"encoding": "jsonParsed"}],
    )
    out = []
    for item in (res or {}).get("value", []):
        info = item["account"]["data"]["parsed"]["info"]
        out.append((item["pubkey"], float(info["tokenAmount"]["uiAmount"] or 0)))
    return out


def owner_deltas(tx, mint):
    """Somme des variations de balance par propriétaire pour un mint donné."""
    deltas = {}
    meta = tx.get("meta") or {}
    for key, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for bal in meta.get(key) or []:
            if bal.get("mint") != mint:
                continue
            owner = bal.get("owner", "?")
            amount = float((bal.get("uiTokenAmount") or {}).get("uiAmount") or 0)
            deltas[owner] = deltas.get(owner, 0.0) + sign * amount
    return deltas


def check_solana_whales(state, price, alerts):
    balances = {}
    for owner in (WHALE_1, WHALE_2):
        for mint in (USDC_MINT, USDT_MINT):
            try:
                accounts = token_accounts(owner, mint)
            except Exception as e:
                print(f"WARN getTokenAccountsByOwner {owner[:8]}/{MINT_NAMES[mint]}: {e}")
                continue
            balances.setdefault(owner, {})[mint] = sum(b for _, b in accounts)

            for acc_pubkey, _bal in accounts:
                last_sig = state["last_sig"].get(acc_pubkey)
                try:
                    sigs = sol_rpc(
                        "getSignaturesForAddress",
                        [acc_pubkey, {"limit": 25, **({"until": last_sig} if last_sig else {})}],
                    ) or []
                except Exception as e:
                    print(f"WARN getSignatures {acc_pubkey[:8]}: {e}")
                    continue

                if last_sig is None:
                    # Premier passage : on mémorise le point de départ sans
                    # alerter sur l'historique.
                    if sigs:
                        state["last_sig"][acc_pubkey] = sigs[0]["signature"]
                    continue

                # sigs est trié du plus récent au plus ancien -> on remet à l'endroit
                new_sigs = [s for s in reversed(sigs)][-MAX_TX_PER_ACCOUNT:]
                for s in new_sigs:
                    sig = s["signature"]
                    if s.get("err") is not None:
                        state["last_sig"][acc_pubkey] = sig
                        continue
                    try:
                        tx = sol_rpc(
                            "getTransaction",
                            [sig, {"encoding": "jsonParsed",
                                   "maxSupportedTransactionVersion": 0}],
                        )
                    except Exception as e:
                        print(f"WARN getTransaction {sig[:12]}: {e}")
                        break  # on retentera au prochain run
                    if tx is None:
                        break
                    state["last_sig"][acc_pubkey] = sig

                    deltas = owner_deltas(tx, mint)
                    my_delta = deltas.get(owner, 0.0)
                    binance_delta = deltas.get(BINANCE_SOL, 0.0)
                    label = WHALE_LABELS[owner]
                    name = MINT_NAMES[mint]
                    when = datetime.fromtimestamp(
                        s.get("blockTime") or time.time(), tz=timezone.utc
                    ).strftime("%d/%m/%Y %H:%M UTC")

                    if my_delta <= -MIN_SOL_TRANSFER:
                        dest = ("→ <b>BINANCE</b> ✅" if binance_delta > 0
                                else "→ destination hors Binance")
                        signal, target = classify_signal(price)
                        msg = (
                            f"🐋 <b>ALERTE WHALE — {label}</b>\n"
                            f"💸 Sortie : <b>{fmt_usd(-my_delta)} {name}</b> {dest}\n"
                            f"🕑 {when}\n"
                            f"₿ BTC : ${fmt_usd(price) if price else '?'}\n\n{signal}"
                        )
                        if target:
                            msg += (f"\n🎯 Zone cible historique : "
                                    f"${fmt_usd(target[0])} – ${fmt_usd(target[1])}")
                        msg += f"\n🔗 solscan.io/tx/{sig}"
                        alerts.append(msg)
                    elif my_delta >= MIN_SOL_TRANSFER:
                        src = ("depuis <b>BINANCE</b>" if binance_delta < 0
                               else "source hors Binance")
                        msg = (
                            f"🐋 <b>RECHARGE WHALE — {label}</b>\n"
                            f"📥 Entrée : <b>{fmt_usd(my_delta)} {name}</b> {src}\n"
                            f"🕑 {when}\n"
                            f"₿ BTC : ${fmt_usd(price) if price else '?'}\n\n"
                            "ℹ️ Historique : une recharge Binance → whale "
                            "(fév 2026, 357M USDT) a coïncidé avec un creux de "
                            "marché, suivie de redéploiements haussiers."
                            f"\n🔗 solscan.io/tx/{sig}"
                        )
                        alerts.append(msg)
    return balances


# ----------------------------------------------------------------------------
# Surveillance Ethereum (Binance Hot Wallet 20)
# ----------------------------------------------------------------------------


def pad_addr(addr):
    return "0x" + "0" * 24 + addr[2:].lower()


def check_binance_hw20(state, price, alerts):
    try:
        latest = int(eth_rpc("eth_blockNumber", []), 16)
    except Exception as e:
        print(f"WARN eth_blockNumber: {e}")
        return

    last_block = state.get("eth_last_block")
    if last_block is None:
        state["eth_last_block"] = latest
        return
    from_block = max(last_block + 1, latest - 5000)
    if from_block > latest:
        return

    seen = set()
    for topics in (
        [TRANSFER_TOPIC, pad_addr(BINANCE_HW20)],          # sorties
        [TRANSFER_TOPIC, None, pad_addr(BINANCE_HW20)],    # entrées
    ):
        try:
            logs = eth_rpc(
                "eth_getLogs",
                [{
                    "address": USDT_ETH,
                    "fromBlock": hex(from_block),
                    "toBlock": hex(latest),
                    "topics": topics,
                }],
            ) or []
        except Exception as e:
            print(f"WARN eth_getLogs: {e}")
            return  # on retentera tout le range au prochain run

        for log in logs:
            key = (log.get("transactionHash"), log.get("logIndex"))
            if key in seen:
                continue
            seen.add(key)
            amount = int(log["data"], 16) / 1e6
            if amount < MIN_ETH_TRANSFER:
                continue
            sender = "0x" + log["topics"][1][-40:]
            receiver = "0x" + log["topics"][2][-40:]
            direction = ("📤 Sortie" if sender == BINANCE_HW20 else "📥 Entrée")
            signal, _ = classify_signal(price)
            alerts.append(
                f"🏦 <b>BINANCE HOT WALLET 20</b> (Ethereum)\n"
                f"{direction} : <b>{fmt_usd(amount)} USDT</b>\n"
                f"De {sender[:10]}… vers {receiver[:10]}…\n"
                f"₿ BTC : ${fmt_usd(price) if price else '?'}\n\n"
                "ℹ️ Historique : les gros mouvements HW20 avec BTC &lt; 92k$ ont "
                "précédé les plus fortes hausses (+15% à +24% en 4 semaines).\n"
                f"{signal}\n"
                f"🔗 etherscan.io/tx/{log.get('transactionHash')}"
            )

    state["eth_last_block"] = latest


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("last_sig", {})
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)
        f.write("\n")


def main():
    state = load_state()
    first_run = not state["last_sig"]
    price = btc_price()
    alerts = []

    balances = check_solana_whales(state, price, alerts)
    check_binance_hw20(state, price, alerts)

    w1_usdc = (balances.get(WHALE_1) or {}).get(USDC_MINT)
    now = time.time()

    if first_run:
        msg = (
            "🤖 <b>Whale Watch démarré</b>\n\n"
            "Surveillance active :\n"
            "• Wallet 1 (H8BgJ…5hss) — USDC/USDT Solana\n"
            "• Wallet 2 (9WzDX…AWWM) — USDC/USDT Solana\n"
            "• Binance Hot Wallet 20 — USDT Ethereum (≥ 150M$)\n\n"
            f"₿ BTC actuel : ${fmt_usd(price) if price else '?'}\n"
        )
        if w1_usdc is not None:
            msg += f"💰 Réserve Wallet 1 : {fmt_usd(w1_usdc)} USDC en attente\n"
        msg += "\nVérification toutes les ~15 min. Vie du bot confirmée chaque semaine."
        send_telegram(msg)
        state["last_heartbeat"] = now
    elif now - state.get("last_heartbeat", 0) > HEARTBEAT_SECS:
        msg = (
            "✅ <b>Whale Watch opérationnel</b> (rapport hebdomadaire)\n"
            f"₿ BTC : ${fmt_usd(price) if price else '?'}\n"
        )
        if w1_usdc is not None:
            msg += f"💰 Réserve Wallet 1 : {fmt_usd(w1_usdc)} USDC\n"
        msg += "Aucune action requise. Les alertes arrivent dès qu'un whale bouge."
        send_telegram(msg)
        state["last_heartbeat"] = now

    for msg in alerts:
        send_telegram(msg)
        time.sleep(1)

    save_state(state)
    print(f"OK — {len(alerts)} alerte(s), BTC={price}, "
          f"{len(state['last_sig'])} comptes suivis.")


if __name__ == "__main__":
    main()
