# Phase 7 — Collecte des données de marché
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 7 en cours de validation.**
**Prérequis : Phases 1 à 6 validées.**
**Décisions de cadrage prises avec l'utilisateur** : premier exchange = **HTX (ex-Huobi)** ; marché = **Spot** par défaut en l'absence de réponse explicite sur ce point — hypothèse posée ici, à confirmer ou corriger (voir §2).

---

## 1. Besoin métier de cette phase

Le moteur ne peut rien décider sans données de marché fiables, à jour, et correctement journalisées dès leur réception. Cette phase construit le **premier maillon réel** de la chaîne définie en Phase 2 : le `data_collector` et son premier `ExchangeAdapter` (HTX).

## 2. Hypothèse posée (à confirmer)

Vous n'avez pas répondu explicitement à la question spot vs. futures. **J'ai retenu Spot par défaut** pour la V1, pour une raison précise : les contrats perpétuels ajoutent une complexité immédiate (funding rate, liquidation, effet de levier) que la Phase 1 a explicitement choisi de différer tant que le socle (collecte, features, décision, risque) n'est pas validé. Le spot suffit pour construire et valider ce socle. **Dites-le-moi si vous préférez les futures dès maintenant** — cela change certains champs du schéma (déjà anticipés en Phase 6 : `funding_rates` existe justement pour ce cas) et certains endpoints HTX.

## 3. Problème technique

Comment collecter en continu, sans perte silencieuse, les trades et le carnet d'ordres HTX pour les paires suivies, tout en respectant strictement la frontière définie en Phase 2 : *le collecteur ne fait aucun calcul, aucune décision, et n'écrit jamais directement dans le stockage métier — il transmet au Normalizer*.

---

## 4. Options de collecte envisagées

| Option | Avantages | Limites | Retenue ? |
|---|---|---|---|
| **Polling REST périodique** | Simple à implémenter | Latence élevée, consomme le quota de rate-limit rapidement, ne capte pas les trades entre deux appels | ❌ Rejetée en flux principal |
| **WebSocket public (trades + depth) en continu, REST utilisé uniquement pour le backfill historique et la resynchronisation** | Faible latence, pas de rate-limit sur le flux temps réel, conforme aux recommandations officielles HTX ("it is suggested to use WebSocket interface") | Nécessite une gestion robuste de reconnexion (déconnexions fréquentes documentées côté HTX) | **✅ Retenue** |

**Décision retenue** : WebSocket public HTX (`wss://api.huobi.pro/ws`, canaux `market.<symbol>.trade.detail` et `market.<symbol>.depth.step0`) comme flux principal, avec REST (`https://api.huobi.pro`) utilisé uniquement pour : (a) le backfill au démarrage, (b) la resynchronisation en cas de trou détecté.

**Point d'attention documenté par HTX lui-même** : le serveur ferme la connexion si le client ne répond pas aux `ping` toutes les 5 secondes (5 tentatives), et peut déconnecter proactivement en cas de charge. Le collecteur doit donc implémenter une reconnexion automatique avec backoff, et **journaliser chaque déconnexion/reconnexion** dans `events_journal` (Phase 4 §5.5) — une perte de connexion silencieuse serait un risque direct pour le moteur de risque (qui doit toujours savoir si les données sont à jour).

---

## 5. Respect de la frontière Collecteur → Normalizer (Phase 2)

Le collecteur **ne transforme pas** le format HTX vers le format interne — il se contente de désérialiser (décompression gzip, parsing JSON) et de publier tel quel sur un canal Redis Pub/Sub dédié (`raw:htx:trade`, `raw:htx:depth`). C'est le **Normalizer (Phase 8)** qui convertira vers le schéma unifié et écrira dans `raw_market_data`/`order_book_snapshots` (Phase 6). Cette séparation stricte est ce qui permettra d'ajouter un deuxième exchange plus tard sans toucher au Normalizer ni au reste du pipeline (objectif d'extensibilité de la Phase 1).

---

## 6. Procédure de création et sécurisation des clés API (demandée dans le brief initial)

Cette procédure est **écrite pour être suivie manuellement par vous**, elle n'est volontairement pas automatisée (créer un compte et des clés API est un acte qui doit rester un geste humain conscient) :

1. **Créer un compte HTX** sur htx.com, compléter la vérification d'identité (KYC) requise pour le trading.
2. **Activer l'authentification à deux facteurs (2FA)** sur le compte avant toute création de clé API — non négociable.
3. Aller dans *Gestion des API* (API Management) du compte.
4. Créer une nouvelle clé API avec :
   - **Permissions : "Lecture" + "Trading" uniquement.** Ne jamais cocher "Retrait" (Withdraw) — aucune fonctionnalité de la plateforme n'en a besoin, et cela élimine le risque de vol de fonds même en cas de fuite de clé.
   - **Restriction IP obligatoire** : renseigner l'adresse IP fixe du VPS Fornex (Phase 3). HTX rejettera toute requête provenant d'une autre IP, même avec la bonne clé/secret.
5. Noter la clé (`Access Key`) et le secret (`Secret Key`) **une seule fois** (HTX ne réaffiche pas le secret après création) directement dans le fichier `.env` du VPS (Phase 5), jamais dans un fichier temporaire, un email, ou un gestionnaire de notes non chiffré.
6. Vérifier immédiatement après création que les permissions affichées correspondent bien à ce qui a été configuré (lecture + trading, pas de retrait, IP restreinte).
7. **Ne jamais partager la clé et le secret ensemble**, y compris avec le support HTX — c'est un principe rappelé explicitement dans la documentation officielle HTX elle-même.

*(Cette procédure ne sera réellement utilisée qu'à partir de la Phase 12 — moteur d'exécution — puisque la Phase 7 ne fait que de la lecture de données publiques, sans authentification. Elle est documentée dès maintenant pour que vous puissiez préparer le compte en parallèle si vous le souhaitez.)*

---

## 7. Fichiers produits dans cette phase

- `backend/shared/exchange_adapter.py` — interface `ExchangeAdapter` (contrat Phase 2, §6).
- `backend/data_collector/adapters/htx.py` — implémentation HTX (WebSocket + REST, marché Spot).
- `backend/data_collector/main.py` — point d'entrée du service collecteur (gestion de connexion, reconnexion, publication des événements de journal).
- `backend/tests/test_htx_adapter.py` — tests unitaires (parsing des messages HTX, gestion de la reconnexion).

---

## 8. Auto-évaluation

**Faiblesses identifiées :**
- Le backfill REST au démarrage n'est pas encore borné dans le temps dans cette implémentation initiale (à paramétrer précisément en Phase 8, quand le Normalizer définira le besoin exact de profondeur historique).
- La gestion des symboles HTX (format natif `btcusdt`, minuscule, sans séparateur) vers un format canonique (`BTC/USDT`) est déléguée entièrement au Normalizer (Phase 8) — cohérent avec la frontière définie, mais signifie que cette phase seule n'est pas testable de bout en bout avec des données déjà exploitables par le Feature Builder.

**Risques de conception :**
- HTX documente des déconnexions fréquentes sous charge serveur — le taux de reconnexion réel ne sera mesuré qu'en conditions réelles. *Mitigation* : alerte prévue en Phase 19 si le nombre de reconnexions dépasse un seuil anormal sur une fenêtre glissante.

**Cohérence avec les phases précédentes :** ✅ respecte strictement la frontière Collecteur/Normalizer (Phase 2), alimente exactement les canaux attendus par le Journal (Phase 4 §5.5), aucune clé API utilisée à ce stade (données publiques uniquement).

---

## 9. Prochaine étape

Phase 8 — Normalisation des données : implémentation du `Normalizer`, mapping des symboles HTX vers le format canonique interne, écriture réelle dans `raw_market_data` et `order_book_snapshots` (Phase 6).
