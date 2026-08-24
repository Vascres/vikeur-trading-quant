import { describe, expect, it } from "vitest";
import {
  lifecycleStatusIsEvictionPath,
  lifecycleStatusLabel,
  lifecycleStatusStyle,
} from "./strategyLifecycle";

describe("strategyLifecycle", () => {
  it("libellé lisible pour chacun des 9 statuts connus", () => {
    expect(lifecycleStatusLabel("experimental")).toBe("Expérimentale");
    expect(lifecycleStatusLabel("suspended")).toBe("Suspendue");
    expect(lifecycleStatusLabel("production")).toBe("Production");
  });

  it("statut null (pas encore initialisée) a un libellé explicite, jamais vide", () => {
    expect(lifecycleStatusLabel(null)).toBe("Non initialisée");
  });

  it("chaque style retourné contient au moins une classe de fond et de texte Tailwind", () => {
    expect(lifecycleStatusStyle("validated")).toMatch(/bg-/);
    expect(lifecycleStatusStyle("validated")).toMatch(/text-/);
    expect(lifecycleStatusStyle(null)).toMatch(/bg-/);
  });

  it("distingue le chemin d'éviction du chemin de promotion", () => {
    expect(lifecycleStatusIsEvictionPath("under_review")).toBe(true);
    expect(lifecycleStatusIsEvictionPath("degraded")).toBe(true);
    expect(lifecycleStatusIsEvictionPath("suspended")).toBe(true);
    expect(lifecycleStatusIsEvictionPath("deprecated")).toBe(true);

    expect(lifecycleStatusIsEvictionPath("registered")).toBe(false);
    expect(lifecycleStatusIsEvictionPath("collecting")).toBe(false);
    expect(lifecycleStatusIsEvictionPath("experimental")).toBe(false);
    expect(lifecycleStatusIsEvictionPath("validated")).toBe(false);
    expect(lifecycleStatusIsEvictionPath("production")).toBe(false);
  });

  it("statut null n'est jamais considéré comme un chemin d'éviction", () => {
    expect(lifecycleStatusIsEvictionPath(null)).toBe(false);
  });
});
