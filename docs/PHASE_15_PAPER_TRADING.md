# Phase 15 — Paper Trading
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 15 en cours de validation.**
**Prérequis : Phases 1 à 14 validées.**

---

## 1. Besoin métier de cette phase

Le brief initial demande un mode simulation « identique au réel », comparable objectivement au trading réel. Cela suppose que les positions soient **réellement suivies** en base — ce qui n'est le cas nulle part encore (signalé en fin de Phase 14) : les modes d'exécution (Phase 12) écrivent des `orders`, jamais de `positions`.

## 2. Problème technique

1. Faire vivre la table `positions` (Phase 6) pour de vrai, en cohérence avec l'hypothèse **spot long-only** actée depuis la Phase 7.
2. Empêcher qu'une décision de vente parte à l'exécution s'il n'y a rien à vendre (vente à découvert impossible en spot).
3. Deux bugs latents découverts en construisant cette phase, corrigés avant d'aller plus loin (§4).
4. Fournir un mécanisme de comparaison paper vs réel (demande explicite du brief initial).

---

## 3. Décision de conception : une vente ferme toujours la position entière

Le dimensionnement (Phase 13, `PositionSizingRule`) calcule une quantité **pour ouvrir** une position (fraction de Kelly du capital disponible). Appliquer ce même calcul à une vente n'aurait pas de sens : la quantité à vendre est celle **déjà détenue**, pas une nouvelle fraction du capital. **Décision retenue** : en V1 (spot long-only), une vente clôture systématiquement la totalité de la position ouverte correspondante, indépendamment de la quantité calculée par le dimensionnement. C'est la logique la plus simple et la moins ambiguë tant qu'une seule position par symbole est autorisée à la fois.

---

## 4. Corrections apportées (deux bugs latents détectés)

1. **`RiskContext` ne portait aucune information sur la position déjà ouverte.** Impossible, jusqu'ici, de bloquer une vente à découvert au niveau du Moteur de risque — le blocage n'aurait eu lieu qu'à l'exécution (trop tard dans la philosophie de la Phase 2 : le risque doit avoir le dernier mot *avant* l'exécution). Un champ `open_position_quantity` est ajouté au contexte, et une nouvelle règle **`SpotNoShortingRule`** rejette toute vente sans position ouverte suffisante.
2. **Les requêtes du Moteur de risque (Phase 13) sur `positions` ne filtraient pas par `execution_mode`.** Exposition, perte journalière et pertes consécutives auraient mélangé des positions paper et réelles si les deux tournaient un jour en parallèle. Corrigé : toutes les requêtes sont désormais filtrées par le mode d'exécution couramment configuré (`EXECUTION_MODE`, Phase 5/12) — cohérent avec le principe déjà en place qu'un déploiement tourne dans un seul mode à la fois.

---

## 5. Suivi réel des positions (`execution_engine/positions.py`)

Après chaque remplissage (`PaperExecutionMode` pour l'instant — `RealExecutionMode` suivra dès que la confirmation de remplissage réel sera implémentée, cf. Phase 12, §6) :
- **Achat** : ouvre une nouvelle position, ou l'agrandit (moyenne pondérée) si une position est déjà ouverte pour ce symbole et ce mode.
- **Vente** : clôture entièrement la position ouverte correspondante (§3), calcule le `realized_pnl`, écrit `positions.status = 'closed'`. Sans position ouverte, l'opération est journalisée comme anomalie — elle ne devrait jamais se produire grâce à `SpotNoShortingRule` (§4), mais ce garde-fou reste une seconde ligne de défense.

---

## 6. Comparaison Paper vs Réel

`backend/paper_trading/comparison.py` interroge les `positions` fermées séparément par `execution_mode` (`paper` vs `real`) sur une période donnée, et **réutilise directement les fonctions de `backtesting/metrics.py`** (Phase 14) pour calculer les mêmes métriques des deux côtés — aucune duplication de logique de calcul. Avec un capital réel encore à zéro à ce stade du projet, cette comparaison n'aura de sens qu'une fois du trading réel activé ; elle est construite maintenant pour être prête ce jour-là, conformément à la demande explicite du brief initial.

---

## 7. Fichiers produits dans cette phase

- `backend/shared/risk_rule.py` **(mis à jour)** — ajout de `open_position_quantity`.
- `backend/risk_engine/rules/spot_no_shorting.py` — nouvelle règle.
- `backend/risk_engine/main.py` **(mis à jour)** — filtrage par `execution_mode`, alimentation du nouveau champ, ajout de la règle à `ACTIVE_RULES`.
- `backend/execution_engine/positions.py` — suivi réel des positions.
- `backend/execution_engine/modes/paper.py` **(mis à jour)** — appelle le suivi de positions après chaque remplissage.
- `backend/paper_trading/comparison.py` — comparaison paper vs réel.
- `backend/tests/test_positions.py`, `test_spot_no_shorting.py`, `test_comparison.py`.

---

## 8. Auto-évaluation

**Faiblesses identifiées :**
- Le mode réel (`RealExecutionMode`) n'appelle pas encore le suivi de positions, faute de confirmation de remplissage fiable (Phase 12, §6) — la comparaison paper vs réel (§6) ne sera donc pleinement exploitable qu'après ce complément, prévu lors du durcissement pré-production (Phase 20) ou d'un retour dédié sur la Phase 12.
- Une seule position ouverte par (symbole, mode) est supportée — cohérent avec l'hypothèse spot long-only, mais à revoir si le pyramidage de positions devient un besoin réel.

**Cohérence avec les phases précédentes :** ✅ ferme le gap signalé en fin de Phase 14 ; les deux corrections (§4) renforcent des garanties déjà posées en Phase 2/13 plutôt que de les contredire.

---

## 9. Prochaine étape

Phase 16 — Machine Learning : premiers modèles prédictifs (Gradient Boosting, LSTM...) venant enrichir — pas remplacer — le moteur à règles explicites, une fois celui-ci validé par le paper trading réel sur plusieurs semaines.
