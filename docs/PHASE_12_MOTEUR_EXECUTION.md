# Phase 12 — Moteur d'exécution des ordres
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 12 en cours de validation.**
**Prérequis : Phases 1 à 11 validées.**

---

## 1. Besoin métier de cette phase

C'est ici que le système peut, pour la première fois, agir sur le marché — ou simuler qu'il le fait. La garantie centrale de la Phase 1 (« ce qui est testé est bien ce qui tourne en réel ») repose entièrement sur cette phase : les 3 modes (backtest/paper/réel) doivent être **strictement interchangeables** derrière une interface commune (Phase 2, §4.7).

## 2. Problème technique

Deux problèmes distincts :
1. Comment garantir qu'un changement de mode n'entraîne **aucune** différence de comportement ailleurs dans le pipeline (Moteur de décision, Moteur de risque) ?
2. Comment activer réellement le trading HTX (`place_order`, `cancel_order`, `get_balances`, laissés en `NotImplementedError` depuis la Phase 7) de façon sûre — signature cryptographique correcte, gestion d'erreurs, jamais de retrait possible ?

## 3. Point de séquencement à connaître

Le schéma (Phase 6) exige qu'un `order` référence toujours un `risk_check_id` **validé** — mais le Moteur de risque n'est construit qu'en **Phase 13**, après celle-ci (ordre du brief initial). Ce n'est pas une incohérence : cette phase construit et teste le Moteur d'exécution **en isolation**, avec des `risk_checks` de test créés directement en base pour les besoins des tests. Le branchement réel Décision → Risque → Exécution ne sera complet qu'à la fin de la Phase 13.

---

## 4. Interface commune `ExecutionMode` (Phase 2, §4.7)

```
ExecutionMode.execute(risk_check_id, exchange, symbol, side, quantity, price=None) -> OrderResult
```

Les trois implémentations :

| Mode | Comportement |
|---|---|
| **Backtest** | Simule un remplissage à partir d'un prix historique fourni en paramètre (pas d'accès réseau), avec un modèle de slippage/frais simple et explicite |
| **Paper** | Utilise le prix de marché **réel courant** (dernière candle/carnet), simule le remplissage sans jamais appeler l'exchange |
| **Réel** | Appelle réellement `ExchangeAdapter.place_order` (HTX) |

Les trois écrivent exactement de la même façon dans `orders` (Phase 6), avec `execution_mode` qui varie — **aucune autre différence de schéma ou de champ**, condition de la garantie de cohérence backtest/paper/réel actée en Phase 2.

**Sélection du mode** : une factory lit la variable `EXECUTION_MODE` (déjà présente dans `.env`, Phase 5) — jamais codé en dur, jamais choisi implicitement.

---

## 5. Activation du trading HTX (signature v2, Phase 7)

La documentation HTX impose, pour chaque appel privé : `AccessKeyId`, `SignatureMethod=HmacSHA256`, `SignatureVersion=2`, `Timestamp` (UTC, format `YYYY-MM-DDTHH:MM:SS`), une chaîne pré-signée `METHODE\nHOST\nCHEMIN\nparamètres_triés_encodés`, hashée en HMAC-SHA256 avec le secret puis encodée en base64. **Pour les requêtes POST (passage d'ordre), seuls ces 4 paramètres d'authentification entrent dans le calcul de signature** — les paramètres de l'ordre lui-même (quantité, prix, symbole) vont dans le corps JSON, pas dans la chaîne signée.

⚠️ **Avertissement honnête** : les noms d'endpoints exacts (`/v1/order/orders/place`, `/v1/account/accounts`, etc.) et certains champs proviennent de la documentation HTX consultée, mais une API d'exchange peut évoluer. **Avant tout passage en mode réel avec du capital, vérifiez ces endpoints contre la documentation HTX à jour** (https://huobiapi.github.io/docs/spot/v1/en/) — ce n'est pas une formalité, c'est une vérification de sécurité de base pour du code qui déplacera de l'argent réel.

---

## 6. Fichiers produits dans cette phase

- `backend/shared/execution_mode.py` — contrat `ExecutionMode` et `OrderResult`.
- `backend/execution_engine/modes/backtest.py`, `paper.py`, `real.py` — les 3 implémentations.
- `backend/execution_engine/factory.py` — sélection du mode via `EXECUTION_MODE`.
- `backend/execution_engine/reconciliation.py` — reconstruction d'état au démarrage (Phase 5, §3.2).
- Mise à jour de `backend/data_collector/adapters/htx.py` — activation de `place_order`, `cancel_order`, `get_balances`.
- `backend/tests/test_execution_engine.py` — tests des 3 modes et de la signature.

---

## 7. Auto-évaluation

**Faiblesses identifiées :**
- Le séquencement Phase 12 avant Phase 13 (§3) signifie que cette phase, seule, ne peut pas être testée de bout en bout avec un vrai flux Décision → Risque → Exécution — assumé, comme prévu par le brief initial.
- Les endpoints HTX précis nécessitent une vérification humaine avant mise en réel (§5) — je ne peux pas garantir avec une certitude absolue qu'ils sont exacts au jour de l'exécution.

**Cohérence avec les phases précédentes :** ✅ les 3 modes respectent exactement le contrat de la Phase 2, §4.7 ; le mécanisme de reconstruction d'état au démarrage opérationnalise la Phase 5, §3.2.

---

## 8. Prochaine étape

Phase 13 — Gestion des risques : `risk_engine` (position sizing, exposition, kill switch), qui produira enfin les `risk_checks` validés permettant de fermer la boucle complète Décision → Risque → Exécution.
