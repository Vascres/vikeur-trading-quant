import { describe, expect, it } from "vitest";
import { barWidthPercent, costModelClearedPercent, stagesByFamily } from "./whyNoTrade";
import type { WhyNoTradeStage } from "./api";

const SAMPLE_FUNNEL: WhyNoTradeStage[] = [
  { stage: "opinions_generated", label: "Avis moteur générés", count: 10 },
  { stage: "skipped_regime", label: "Écartés — régime", count: 3 },
  { stage: "no_opinion", label: "Écartés — aucun avis", count: 2 },
  { stage: "excluded_lifecycle", label: "Écartés — lifecycle", count: 1 },
  { stage: "decisions_fused", label: "Décisions fusionnées", count: 4 },
  { stage: "rejected_conviction", label: "Rejetées — conviction", count: 3 },
  { stage: "passed_to_risk_engine", label: "Transmises au Risk Engine", count: 1 },
  { stage: "rejected_risk_engine", label: "Refusées par le Risk Engine", count: 1 },
  { stage: "orders_executed", label: "Ordres exécutés", count: 0 },
];

describe("whyNoTrade", () => {
  it("sépare correctement les deux familles d'étages, jamais mélangées", () => {
    const { engineLevel, decisionLevel } = stagesByFamily(SAMPLE_FUNNEL);
    expect(engineLevel.map((s) => s.stage)).toEqual([
      "opinions_generated",
      "skipped_regime",
      "no_opinion",
      "excluded_lifecycle",
    ]);
    expect(decisionLevel.map((s) => s.stage)).toEqual([
      "decisions_fused",
      "rejected_conviction",
      "passed_to_risk_engine",
      "rejected_risk_engine",
      "orders_executed",
    ]);
  });

  it("largeur de barre à 100% quand count == référence", () => {
    expect(barWidthPercent(10, 10)).toBe(100);
  });

  it("largeur de barre proportionnelle à la référence", () => {
    expect(barWidthPercent(3, 10)).toBe(30);
  });

  it("largeur de barre à 0 quand la référence est nulle, jamais une division par zéro", () => {
    expect(barWidthPercent(5, 0)).toBe(0);
  });

  it("largeur de barre jamais négative ni supérieure à 100", () => {
    expect(barWidthPercent(-5, 10)).toBe(0);
    expect(barWidthPercent(15, 10)).toBe(100);
  });

  it("pourcentage cost model calculé correctement", () => {
    expect(costModelClearedPercent(2, 4)).toBe(50);
  });

  it("pourcentage cost model est null quand total == 0, jamais NaN", () => {
    expect(costModelClearedPercent(0, 0)).toBeNull();
  });
});
