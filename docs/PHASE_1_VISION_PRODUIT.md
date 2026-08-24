# Phase 1 — Vision produit et cahier des charges
## Plateforme quantitative de trading crypto — Version V1 réaliste

**Statut : Phase 1 en cours de validation — aucun code ne sera écrit avant validation de ce document.**
**Auteur : Claude (rôle CTO / Software Architect), en collaboration avec le porteur de projet.**

---

## 0. Remarque préalable du CTO — cohérence entre ambition et contexte

Le brief initial décrit une plateforme de niveau institutionnel (10 exchanges, Kafka, Kubernetes, 9 modèles ML en compétition, centaines de stratégies simultanées, moteur 24/7 multi-actifs). Les réponses de cadrage indiquent :

- **Utilisateur unique**, pas d'équipe, pas de SaaS pour l'instant.
- **Capital de trading < 10 000 $.**
- **Infrastructure minimale** au démarrage.

Une architecture "institutionnelle" appliquée à ce contexte serait une erreur de conception, pour trois raisons concrètes :

1. **Coût/bénéfice négatif.** Kafka, Kubernetes, TimescaleDB en cluster, 10 connecteurs d'exchange maintenus en parallèle : c'est des semaines de travail d'infrastructure pour un compte qui ne génère pas encore de quoi les justifier. Le risque principal à ce stade n'est pas le manque de scalabilité, c'est de ne jamais finir la V1.
2. **Maintenabilité solo.** Une personne seule ne peut pas opérer 24/7 un système distribué complexe (Kafka + K8s + 10 exchanges) sans astreinte, sans équipe SRE, sans budget cloud conséquent. Un incident non détecté à 3h du matin sur un système sous-maintenu, avec du capital réel en jeu, est plus dangereux qu'un système simple bien surveillé.
3. **Sur-ajustement (overfitting) du risque business avant même le risque de marché.** Avec <10k$, les frais, le slippage et les limites de liquidité dominent largement la performance. La priorité n°1 n'est pas la sophistication du modèle ML, c'est une exécution propre à faible coût sur un nombre restreint d'actifs liquides.

**Décision retenue :** je conserve **l'intégralité de la vision long terme** (elle reste l'objectif à 2-3 ans et structure les Phases 2 à 20), mais je découpe la V1 en un socle volontairement plus modeste, conçu dès le départ pour ne jamais nécessiter de réécriture — seulement des extensions. C'est un principe d'architecture logicielle standard ("start simple, design for extension") et c'est cohérent avec votre propre règle : *"la plateforme peut évoluer pendant plusieurs années sans réécriture majeure"*.

Le tableau en section 6 détaille précisément ce qui est V1 vs. ce qui est différé, et pourquoi.

---

## 1. Définition du besoin métier

### 1.1 Problème à résoudre
Un trader individuel gérant un capital propre limité (<10k$) n'a pas les moyens :
- de surveiller manuellement les marchés crypto 24h/24 ;
- d'évaluer objectivement, en continu, l'espérance mathématique de ses décisions (frais, slippage, liquidité inclus) ;
- de tester rigoureusement une stratégie avant de l'exposer à du capital réel ;
- de garder une discipline de gestion du risque constante (pas d'émotion, pas de fatigue).

### 1.2 Proposition de valeur
Construire un système qui **prend des décisions de trading systématiques, mesurables et explicables**, avec une gestion du risque stricte, capable de tourner sans surveillance humaine constante, et dont chaque composant peut être audité (pourquoi cette position a-t-elle été prise, ou pas prise).

### 1.3 Ce que le produit n'est pas
- Ce n'est pas un système de prédiction "magique" du marché.
- Ce n'est pas, en V1, un produit destiné à d'autres utilisateurs (le multi-tenant SaaS est un objectif Phase 17+ si le besoin apparaît).
- Ce n'est pas un système haute fréquence (latence sub-milliseconde) : à ce stade, l'edge visé est sur des horizons allant de la minute à plusieurs heures, où la latence réseau standard est largement suffisante.

---

## 2. Utilisateurs cibles

| Profil | V1 | Évolution future |
|---|---|---|
| Vous (opérateur unique, propriétaire du capital) | ✅ Utilisateur unique, accès total | reste l'utilisateur principal |
| Autres traders individuels (SaaS) | ❌ Hors périmètre V1 | Envisageable Phase 17+ si le moteur est rentable et stable sur ≥6-12 mois |
| Société de trading / fonds | ❌ Hors périmètre | Envisageable si le besoin business apparaît |

---

## 3. Objectifs métier (business)

1. **Objectif n°1 — Ne pas perdre le capital par erreur systémique.** La priorité absolue est la maîtrise du risque, pas la performance brute.
2. **Objectif n°2 — Espérance mathématique positive et mesurée**, nette de tous les coûts (frais, slippage, financement).
3. **Objectif n°3 — Explicabilité totale.** Chaque décision (prise ou refusée) doit être traçable a posteriori : quelles variables, quel score, quel seuil.
4. **Objectif n°4 — Autonomie opérationnelle.** Le système doit pouvoir tourner plusieurs jours sans intervention, avec alerte immédiate en cas d'anomalie.
5. **Objectif n°5 — Base extensible.** Chaque brique construite en V1 doit pouvoir accueillir, sans réécriture, les extensions prévues aux phases suivantes (exchanges supplémentaires, modèles ML additionnels, capital plus important).

---

## 4. Objectifs techniques

1. Collecter et historiser proprement les données de marché d'**un nombre restreint d'exchanges au départ** (voir §6), avec une interface d'ingestion générique permettant d'en ajouter d'autres sans modifier le cœur du système (pattern *adapter/plugin*).
2. Construire un pipeline de features réutilisable et versionné (traçabilité : quelle version de feature a servi à quelle décision).
3. Un moteur de décision basé sur des règles quantitatives explicites et mesurables **avant** d'introduire du Machine Learning — le ML vient enrichir un système qui fonctionne déjà de façon déterministe et auditable, pas le remplacer dès le départ.
4. Un moteur de risque strict et non contournable (kill switch, limites de perte, position sizing) placé en dernière ligne, indépendant du moteur de décision.
5. Un moteur de backtesting fiable **avant** tout trading réel — aucune stratégie ne passe en réel sans avoir été validée en backtest puis en paper trading sur une durée définie.
6. Une infrastructure conteneurisée (Docker) simple, monitorée, avec sauvegardes automatiques — sans complexité distribuée (Kafka/K8s) tant que le volume de données et le nombre d'actifs ne le justifient pas objectivement.

---

## 5. Contraintes

### 5.1 Contraintes fonctionnelles
- Le système doit pouvoir fonctionner en 3 modes strictement séparés : **backtest**, **paper trading**, **trading réel** — avec le même code de moteur de décision (pour garantir que ce qui est testé est bien ce qui tourne en réel).
- Aucune position réelle ne peut être ouverte sans passage préalable des contrôles de risque (fonds insuffisants, liquidité, slippage estimé, exposition max).
- Toute décision (prise ou rejetée) doit être journalisée avec les valeurs des variables ayant mené à la décision.
- Le système doit pouvoir être arrêté manuellement à tout moment (kill switch) sans laisser de position orpheline non gérée.

### 5.2 Contraintes non-fonctionnelles
- **Coût infra** : objectif V1 = infrastructure exploitable pour quelques dizaines d'euros/mois maximum (VPS unique ou petit cloud managé), pas de cluster.
- **Fiabilité** : le système doit détecter et signaler ses propres pannes (perte de connexion exchange, données manquantes, dérive de performance) — pas de silence en cas d'erreur.
- **Sécurité** : clés API en permissions minimales (trading seul, jamais de retrait), secrets jamais en clair dans le code ou les logs.
- **Maintenabilité solo** : toute complexité ajoutée doit être justifiée par un besoin réel constaté, pas par anticipation ("YAGNI" — *You Aren't Gonna Need It*).
- **Réversibilité** : chaque exchange, chaque modèle, chaque stratégie doit pouvoir être désactivé indépendamment sans affecter le reste du système.

### 5.3 Contraintes réglementaires et éthiques
- Usage strictement personnel du capital propre en V1 — pas de gestion de fonds de tiers (ce qui changerait radicalement le cadre réglementaire).
- Respect des conditions d'utilisation de chaque exchange (rate limits API, interdiction de wash trading, etc.).

---

## 6. Périmètre V1 vs. vision long terme (élément central du cahier des charges)

| Sujet | Vision long terme (brief initial) | **V1 retenue** | Justification |
|---|---|---|---|
| Exchanges | 10 exchanges | **1 exchange pour démarrer** (le plus liquide, le moins cher en frais — à confirmer ensemble en Phase 6), architecture en adaptateurs pour en ajouter facilement | Un seul connecteur bien testé vaut mieux que 10 approximatifs ; le pattern adapter permet d'ajouter le 2e sans réécrire |
| Actifs suivis | Centaines de cryptos | **5 à 15 paires liquides (majors)** | Avec <10k$, la liquidité et les frais dominent ; suivre 300 paires n'apporte rien tant que l'exécution sur 10 n'est pas maîtrisée |
| Infra données | Kafka, TimescaleDB cluster | **PostgreSQL/TimescaleDB mono-instance**, Redis pour le cache/temps réel | Kafka se justifie à partir de plusieurs dizaines de milliers de messages/sec ; très loin du besoin V1 |
| Orchestration | Kubernetes | **Docker Compose** | K8s ajoute une charge opérationnelle qu'un opérateur seul ne peut pas assumer correctement sans SRE dédié |
| Moteur de décision | ML multi-modèles (9 architectures) | **Moteur à règles quantitatives explicites et scorées** (probabilité, risque, espérance) en V1 ; ML introduit en Phase 16 une fois le socle validé | Un système déterministe est auditable et débuggable ; le ML sans base solide de features/backtesting fiable est une source de faux signaux |
| Stratégies simultanées | Centaines | **1 à 3 stratégies**, comparées objectivement | Il faut valider la méthodologie de comparaison avant de la faire passer à l'échelle |
| Frontend | Dashboard premium temps réel | **Dashboard simple mais fonctionnel** (positions, PnL, logs, kill switch) dès la V1 ; enrichissement visuel progressif | La priorité est l'observabilité fonctionnelle, pas l'esthétique, en V1 |
| Sentiment/on-chain/macro | Inclus dès le départ | **Différé** (Phase 9 avancée ou ultérieure) | Ces signaux sont difficiles à valider statistiquement et ajoutent du bruit si le socle prix/carnet n'est pas déjà solide |

**Ce qui ne change pas et reste non négociable dès la V1 :**
- Séparation stricte backtest / paper / réel avec le même moteur.
- Risk management indépendant et prioritaire sur toute autre logique.
- Journalisation complète et explicabilité des décisions.
- Architecture en modules indépendants (dès la Phase 2), pour que l'ajout d'un exchange, d'une stratégie ou d'un modèle ne touche jamais le cœur du système.

---

## 7. Critères de succès de la V1

La V1 sera considérée réussie si, et seulement si :

1. Le système tourne en **paper trading** de façon autonome pendant au moins **4 à 8 semaines** sans intervention corrective majeure.
2. Chaque décision (prise ou rejetée) est **journalisée et explicable** a posteriori.
3. Le moteur de risque a été **testé en conditions dégradées** (perte de connexion exchange, données manquantes, mouvement de marché extrême simulé) sans jamais laisser une position non gérée.
4. Le backtest et le paper trading produisent des résultats **cohérents entre eux** (pas d'écart inexpliqué de performance).
5. Ajouter un deuxième exchange ou une deuxième stratégie **ne nécessite pas de réécriture** du moteur central (validation directe de l'objectif d'extensibilité).
6. Le passage en trading réel ne se fait qu'après validation explicite de tous les points ci-dessus — jamais par défaut.

## 8. Indicateurs de performance (KPI) à instrumenter dès la V1

- **KPI techniques** : disponibilité du moteur (uptime), latence de décision, taux d'erreurs de collecte de données, taux de désynchronisation paper vs réel.
- **KPI financiers** (mesurés d'abord en backtest, puis paper) : Sharpe, Sortino, Max Drawdown, Profit Factor, Expectancy — définis en détail en Phase 14.
- **KPI de risque** : nombre de fois où le kill switch ou les limites de perte ont été déclenchés, exposition max atteinte vs. limite configurée.
- **KPI d'explicabilité** : % de décisions pour lesquelles le journal permet de reconstituer entièrement le raisonnement (objectif : 100 %).

---

## 9. Prochaine étape

Une fois ce document validé (ou amendé selon vos retours), nous passerons à la **Phase 2 — Architecture logicielle** : définition des modules, des responsabilités, des flux de données, des interfaces entre composants, et premiers diagrammes d'architecture — toujours calibrés sur le périmètre V1 défini en section 6, mais conçus pour supporter l'extension vers la vision long terme.

---

*Document à valider avant toute décision d'architecture ou toute ligne de code.*
