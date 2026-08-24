"""Estimation de l'espérance et du ratio rendement/risque (ADR-0010, ADR-0016,
étendu par le chantier CostModel unique du 16/08/2026).

Relocalisé depuis l'ancienne stratégie unique : ces grandeurs dépendent
de faits de marché (coût du spread, volatilité), pas de l'opinion d'un
moteur spécifique - elles n'appartiennent donc plus à un `DecisionEngine`
individuel (cf. `shared/decision_engine.py`), mais sont calculées une
seule fois par l'orchestrateur, à partir des features brutes.

Fonctions pures, partagées entre `decision_engine/main.py` (live) et
`backtesting/engine.py` - le même code path, jamais dupliqué (principe
déjà en place, salué par l'audit, préservé par ce chantier).

ADR-0016 : `estimate_expected_value` nette désormais un coût de frais
round-trip réel (mesuré via `cost_model`, ADR-0016) en plus du spread -
avant ce chantier, aucun frais n'était jamais soustrait ici, seul le
Risk Engine (`liquidity_slippage_fees.py`) appliquait un filtre de frais,
sur une constante non mesurée et non synchronisée avec ce calcul (bug
identifié lors du diagnostic du 1er août). Par défaut (`round_trip_fee_bps
= 0.0`), le comportement reste inchangé pour tout appelant qui ne
fournirait pas encore de frais mesurés - jamais un changement de
comportement silencieux pour du code non mis à jour.

Chantier CostModel unique (16/08/2026) : `evaluate_costs` généralise ce
calcul (edge brut -> frais -> impact funding -> edge net) en une seule
fonction pure testée en isolation, pour qu'il n'existe plus qu'un seul
endroit où "edge net après coûts" est défini (cf. audit du 16/08/2026,
§"CostModel unique" - avant ce chantier, `decision_engine/main.py`
recalculait `net_margin_bps` séparément de `expected_value`, deux
expressions mathématiquement équivalentes mais non synchronisées par un
test, exactement le type de dérive qu'ADR-0016 visait déjà à éliminer
pour les frais). `estimate_expected_value` délègue désormais à
`evaluate_costs` en interne - résultat strictement identique (vérifié
par test de non-régression), aucun changement de comportement pour les
appelants existants.

Limitation assumée (héritée de l'ancienne stratégie, pas nouvelle) : ces
estimations restent des approximations simples (pas de simulation
d'exécution complète - carnet d'ordres, délai de remplissage) - le futur
module `execution_simulator` (Architecture Cible V2, §3.4) les
remplacera par une estimation plus riche, sans changer ce point de
branchement. Le slippage réel (mesuré via le carnet d'ordres) reste
vérifié séparément par le Risk Engine, qui a seul accès au carnet en
temps réel à l'instant de la décision (cf. ADR-0016 §3.2) - `evaluate_costs`
ne réintroduit volontairement aucune matrice de slippage statique en
parallèle de cette mesure déjà réelle (walk du carnet, `risk_engine/rules/
liquidity_slippage_fees.py`) : la dupliquer avec une estimation plus
grossière serait une régression, pas une amélioration, pour tout moteur
qui passe déjà par le Risk Engine. Une estimation de slippage ex-ante
(avant même la Risk Engine) reste une extension possible pour un futur
agent qui en aurait besoin (ex. triage rapide d'opportunités avant
d'atteindre le carnet réel), mais n'est pas construite spéculativement
ici tant qu'aucun consommateur réel ne l'exige.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostEvaluation:
    """Décomposition complète edge brut -> edge net (chantier CostModel
    unique) - chaque composante reste visible séparément, jamais
    fusionnée en une seule opération opaque (Principe 1 du mandat :
    "aucune boîte noire")."""

    raw_edge_bps: float
    spread_bps: float
    fee_bps: float
    funding_impact_bps: float
    net_edge_bps: float
    cleared_costs: bool


def compute_funding_impact_bps(
    funding_rate_bps: float,
    expected_holding_period_hours: float,
    direction_sign: int,
    funding_settlement_period_hours: float = 8.0,
) -> float:
    """Impact du funding sur l'espérance nette, proportionnel au nombre
    de règlements couverts par la durée de détention attendue
    (`expected_holding_period_hours / funding_settlement_period_hours`) -
    jamais une seule période comparée à un coût d'ouverture complet.

    C'est précisément l'erreur identifiée dans le modèle économique
    d'origine du funding/basis (ADR-0021, audit du 16/08/2026) :
    comparer le funding d'un seul règlement de 8h au coût complet
    d'ouverture d'une paire, alors qu'une position de portage encaisse
    potentiellement plusieurs règlements sur sa durée de détention. Le
    correctif de cette erreur précise (funding/basis) reste un chantier
    séparé (`pair_execution`) - cette fonction n'est que le calcul
    générique et testé qu'il consommera, réutilisable par tout futur
    agent qui détiendrait une position exposée au funding (futures
    directionnels, cash-and-carry).

    `direction_sign` : +1 si la position reçoit le funding (encaissé,
    augmente l'edge net), -1 si elle le paie (coûte, diminue l'edge
    net). 0 si la position n'a aucune exposition au funding (spot pur).
    """
    settlements_covered = expected_holding_period_hours / funding_settlement_period_hours
    return funding_rate_bps * settlements_covered * direction_sign


def evaluate_costs(
    raw_edge_bps: float,
    spread_bps: float = 0.0,
    round_trip_fee_bps: float = 0.0,
    funding_rate_bps: float | None = None,
    expected_holding_period_hours: float = 0.0,
    funding_direction_sign: int = 0,
) -> CostEvaluation:
    """Fonction pure unifiée (chantier CostModel unique, 16/08/2026) :
    edge brut -> spread -> frais -> impact funding (si applicable) ->
    edge net -> couverture des coûts (`cleared_costs`).

    Généralise et remplace le calcul ad hoc auparavant recalculé en
    ligne dans `decision_engine/main.py` (frais seuls, jamais de
    funding) - sans changer son résultat pour l'usage actuel (aucun
    moteur actif ne fournit encore `funding_rate_bps`/
    `expected_holding_period_hours`, l'impact funding reste donc nul par
    défaut, comportement strictement identique à avant ce chantier).
    """
    funding_impact_bps = 0.0
    if funding_rate_bps is not None and expected_holding_period_hours > 0:
        funding_impact_bps = compute_funding_impact_bps(
            funding_rate_bps, expected_holding_period_hours, funding_direction_sign
        )

    net_edge_bps = raw_edge_bps - spread_bps - round_trip_fee_bps + funding_impact_bps
    return CostEvaluation(
        raw_edge_bps=raw_edge_bps,
        spread_bps=spread_bps,
        fee_bps=round_trip_fee_bps,
        funding_impact_bps=funding_impact_bps,
        net_edge_bps=net_edge_bps,
        cleared_costs=net_edge_bps > 0,
    )


def estimate_expected_value(features: dict[str, float], round_trip_fee_bps: float = 0.0) -> float | None:
    momentum = features.get("momentum")
    spread_bps = features.get("spread_bps")
    if momentum is None or spread_bps is None:
        return None

    evaluation = evaluate_costs(
        raw_edge_bps=abs(momentum) * 10_000,
        spread_bps=spread_bps,
        round_trip_fee_bps=round_trip_fee_bps,
    )
    return evaluation.net_edge_bps / 10_000


def estimate_risk_reward_ratio(features: dict[str, float]) -> float | None:
    momentum = features.get("momentum")
    volatility = features.get("realized_volatility")
    if momentum is None or volatility is None or volatility <= 0:
        return None

    return abs(momentum) / volatility
