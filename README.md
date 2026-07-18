# 🐋 Whale Watch — Signaux d'achat BTC par surveillance de wallets

Bot Telegram **100 % gratuit, sans serveur, sans dépendance**, hébergé sur
GitHub Actions (gratuit à vie pour un dépôt public). Il surveille les 3 wallets
identifiés dans l'analyse on-chain et envoie un signal d'achat BTC sur Telegram
quand le pattern historique se déclenche.

## 📊 Ce que le bot surveille

| Signal | Chaîne | Rôle | Alerte si |
|---|---|---|---|
| `H8BgJ…5hss` (Wallet 1) | Solana | Whale, grosse réserve USDC | transfert USDC/USDT ≥ 10M$ (entrée ou sortie) |
| `9WzDX…AWWM` (Wallet 2) | Solana | Whale SOL, même compte Binance | transfert USDC/USDT ≥ 10M$ |
| `0x2213…bc9e` (Whale ETH) | Ethereum | Whale en DCA USDT → Binance 14 | transfert USDT ≥ 10M$ |
| `0x28C6…1d60` (Binance 14) | Ethereum | Wallet de dépôt Binance | dépôt externe USDT ≥ 50M$ |
| `0xF977…aceC` (Binance HW20) | Ethereum | Réservoir central Binance | mouvement USDT ≥ 150M$ |
| Tether (mint + trésorerie) | Ethereum | Émetteur du USDT | impression ≥ 50M$, ou USDT frais → Binance ≥ 50M$ |

## 🚦 Règles de signal (issues de l'analyse historique)

- 🟢 **BTC < 90 000 $** + dépôt whale → Binance = **SIGNAL D'ACHAT FORT**
  (historiquement +5 % à +16 % en 2-4 semaines, tous les cas observés)
- 🟡 **BTC entre 90k et 100k** = signal modéré, résultats mixtes
- 🔴 **BTC > 100 000 $** = prudence : les mêmes dépôts ont précédé des baisses
  de −8 % à −27 % (distribution, pas accumulation)
- 📥 **Recharge Binance → whale** = possible creux de marché (pattern fév 2026)

Le bot envoie aussi un message de démarrage et un **rapport quotidien vers
12h (heure de Paris)** — prix BTC, zone de signal, réserves des whales et
état des 6 signaux — pour que tu saches qu'il tourne toujours.

---

## 🚀 Installation (15 minutes, une seule fois)

### Étape 1 — Créer le bot Telegram

1. Dans Telegram, ouvre **@BotFather** (vérifie la coche bleue officielle).
2. Envoie `/newbot`, choisis un nom puis un identifiant (ex. `MonWhaleWatchBot`).
3. BotFather te donne un **token** du type `123456789:AAH...`.
   **Ne le partage JAMAIS, ne le colle jamais dans le code.**
4. Durcissement (important, vu le piratage précédent) :
   - `/setjoingroups` → **Disable** (personne ne peut ajouter ton bot à un groupe)
   - `/setprivacy` → **Enable**

### Étape 2 — Récupérer ton chat_id

1. Envoie n'importe quel message à ton nouveau bot (ex. « salut »).
2. Ouvre dans ton navigateur (remplace `<TOKEN>` par ton token) :
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Repère `"chat":{"id":123456789,...}` → ce nombre est ton **chat_id**.

### Étape 3 — Mettre le code sur GitHub

1. Crée un compte sur [github.com](https://github.com) si besoin.
2. Crée un nouveau dépôt (bouton **New**) : nom libre (ex. `whale-watch`),
   visibilité **Public** (= minutes GitHub Actions illimitées et gratuites à vie ;
   le code ne contient aucun secret, uniquement des adresses déjà publiques
   sur la blockchain).
3. Sur ton PC, dans ce dossier, exécute (PowerShell) :

   ```powershell
   git remote add origin https://github.com/TON_PSEUDO/whale-watch.git
   git push -u origin main
   ```

   > Alternative si le dépôt doit être **privé** : c'est possible, mais passe le
   > cron à `*/30 * * * *` dans `.github/workflows/whale-watch.yml` pour rester
   > sous les 2 000 minutes gratuites/mois.

### Étape 4 — Ajouter les secrets (le cœur de la sécurité)

1. Sur la page GitHub du dépôt : **Settings → Secrets and variables → Actions**.
2. Bouton **New repository secret**, deux fois :
   - Nom : `TELEGRAM_BOT_TOKEN` → valeur : le token de BotFather
   - Nom : `TELEGRAM_CHAT_ID` → valeur : ton chat_id
3. Les secrets sont chiffrés par GitHub, invisibles dans le code, les logs et
   pour toute personne qui consulte le dépôt.

### Étape 5 — Activer et tester

1. Onglet **Actions** du dépôt → si GitHub demande d'activer les workflows,
   clique **Enable**.
2. Clique sur **Whale Watch** (à gauche) → bouton **Run workflow** → **Run**.
3. En ~1 minute tu reçois le message « 🤖 Whale Watch démarré » sur Telegram.
4. C'est terminé : le bot tourne ensuite tout seul toutes les ~15 minutes,
   pour toujours, sans PC allumé.

---

## 🔒 Pourquoi ce bot ne peut pas être piraté comme le précédent

La plupart des bots Telegram se font pirater parce qu'ils **écoutent** :
un serveur qui tourne 24/7, un webhook exposé sur Internet, des commandes
entrantes traitées sans vérification, ou un token écrit en clair dans le code.

Ce bot élimine toutes ces surfaces d'attaque :

1. **Aucun serveur, aucun port ouvert** — le code s'exécute 1 min toutes les
   15 min dans une machine virtuelle GitHub jetable, détruite après chaque run.
2. **Communication sortante uniquement** — le bot *envoie* des messages ; il ne
   lit jamais ce qu'on lui écrit. Impossible de l'attaquer par commande.
3. **Token jamais dans le code** — uniquement dans les GitHub Secrets chiffrés.
   Même toi tu ne peux plus le relire après l'avoir enregistré.
4. **Zéro dépendance externe** — 100 % bibliothèque standard Python. Aucun
   paquet npm/pip qui pourrait être compromis (attaque supply-chain).
5. **Action GitHub épinglée sur un commit SHA** — même si `actions/checkout`
   était compromis demain, le bot utiliserait toujours la version vérifiée.
6. **Permissions minimales** — le workflow n'a que le droit d'écrire
   `state.json` dans son propre dépôt, rien d'autre.
7. **Données envoyées : uniquement vers `api.telegram.org`** — aucune autre
   destination, aucune donnée personnelle ne circule.

### Réflexes de sécurité à garder

- Si tu penses que ton **ancien token** (bot piraté) est encore actif :
  BotFather → `/mybots` → ancien bot → **Revoke token** ou supprime le bot.
- Ne réutilise jamais un token existant pour ce bot : crée-en un neuf.
- Active la **validation en 2 étapes** sur Telegram ET sur GitHub.
- Si un jour tu soupçonnes une fuite : BotFather → `/revoke` → nouveau token
  → mets à jour le secret GitHub. 2 minutes, aucune autre conséquence.

---

## 🧪 Tester en local (optionnel)

```powershell
python watcher.py --dry-run
```

Affiche dans le terminal ce qui serait envoyé sur Telegram, sans rien envoyer
(aucun token nécessaire).

## ⚠️ Avertissement

Ce bot signale des mouvements on-chain corrélés historiquement au prix du BTC.
**La corrélation n'est pas une causalité** : les whales peuvent changer de
stratégie, et aucun signal ne garantit une hausse. Ce n'est pas un conseil
financier — n'investis que ce que tu peux te permettre de perdre.
