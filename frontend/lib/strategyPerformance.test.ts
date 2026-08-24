import { describe, expect, it } from "vitest";
import { formatDrawdownPct, formatRatio, isRatioSampleReliable } from "./strategyPerformance";

describe("strategyPerformance", () => {
  it("formatRatio affiche deux décimales", () => {
    expect(formatRatio(1.5)).toBe("1.50");
    expect(formatRatio(-0.333)).toBe("-0.33");
  });

  it("formatRatio affiche un tiret pour une valeur nulle, jamais 'null'", () => {
    expect(formatRatio(null)).toBe("—");
  });

  it("formatDrawdownPct affiche un pourcentage à une décimale", () => {
    expect(formatDrawdownPct(-12.34)).toBe("-12.3%");
  });

  it("formatDrawdownPct affiche un tiret pour une valeur nulle", () => {
    expect(formatDrawdownPct(null)).toBe("—");
  });

  it("échantillon jugé fiable à partir de 30 jours observés", () => {
    expect(isRatioSampleReliable(30)).toBe(true);
    expect(isRatioSampleReliable(29)).toBe(false);
    expect(isRatioSampleReliable(0)).toBe(false);
  });
});
