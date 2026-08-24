import type { WhyNoTradeStage } from "./api";

// Mandat §21 ("Why No Trade") - deux familles d'étages, PAS un seul
// entonnoir continu : les étages "moteur" (par avis individuel) et
// "décision" (par décision fusionnée, plusieurs avis par décision) ne
// partagent pas la même unité de compte - un moteur d'avis et une
// décision fusionnée ne sont jamais directement comparables (cf.
// backend/api/main.py::get_why_no_trade, docstring). Fusionner les deux
// familles dans une seule barre continue impliquerait silencieusement
// que chaque étage est un sous-ensemble strict du précédent, ce qui est
// faux.
export const ENGINE_LEVEL_STAGES = ["opinions_generated", "skipped_regime", "no_opinion", "excluded_lifecycle"];
export const DECISION_LEVEL_STAGES = [
  "decisions_fused",
  "rejected_conviction",
  "passed_to_risk_engine",
  "rejected_risk_engine",
  "orders_executed",
];

export function stagesByFamily(funnel: WhyNoTradeStage[]): {
  engineLevel: WhyNoTradeStage[];
  decisionLevel: WhyNoTradeStage[];
} {
  return {
    engineLevel: funnel.filter((s) => ENGINE_LEVEL_STAGES.includes(s.stage)),
    decisionLevel: funnel.filter((s) => DECISION_LEVEL_STAGES.includes(s.stage)),
  };
}

// Largeur de barre en % relative au premier étage de sa propre famille
// (jamais relative à un total global inter-familles, cf. ci-dessus).
export function barWidthPercent(count: number, referenceCount: number): number {
  if (referenceCount <= 0) return 0;
  const pct = (count / referenceCount) * 100;
  return Math.max(0, Math.min(100, pct));
}

export function costModelClearedPercent(cleared: number, total: number): number | null {
  if (total <= 0) return null;
  return (cleared / total) * 100;
}
