import { describe, expect, it } from "vitest";
import { createSessionValue, verifySessionValue, verifySessionValueVerbose } from "./session";

describe("session", () => {
  const secret = "test-secret";

  it("accepte une session valide et non expirée", async () => {
    const now = Date.now();
    const value = await createSessionValue(secret, now);
    const result = await verifySessionValue(secret, value, now + 1000);
    expect(result).toBe(true);
  });

  it("rejette une signature altérée", async () => {
    const now = Date.now();
    const value = await createSessionValue(secret, now);
    // Remplace toujours les 2 derniers caractères par une valeur
    // GARANTIE différente de l'originale - "00" en dur pouvait, par
    // coïncidence (~1/256), déjà être la fin de la vraie signature,
    // rendant "tampered" strictement identique à "value" et faisant
    // échouer ce test de façon capricieuse (pas un bug de session.ts,
    // un bug du test lui-même, découvert en CI).
    const lastTwoChars = value.slice(-2);
    const replacement = lastTwoChars === "00" ? "ff" : "00";
    const tampered = value.slice(0, -2) + replacement;
    const result = await verifySessionValue(secret, tampered, now);
    expect(result).toBe(false);
  });

  it("rejette une session expirée", async () => {
    const now = Date.now();
    const value = await createSessionValue(secret, now);
    const eightDaysLater = now + 8 * 24 * 60 * 60 * 1000;
    const result = await verifySessionValue(secret, value, eightDaysLater);
    expect(result).toBe(false);
  });

  it("rejette un cookie absent", async () => {
    const result = await verifySessionValue(secret, undefined);
    expect(result).toBe(false);
  });

  it("rejette un secret différent", async () => {
    const now = Date.now();
    const value = await createSessionValue("secret-a", now);
    const result = await verifySessionValue("secret-b", value, now);
    expect(result).toBe(false);
  });
});

describe("verifySessionValueVerbose", () => {
  const secret = "test-secret";

  it("distingue un cookie absent d'une signature invalide", async () => {
    const absent = await verifySessionValueVerbose(secret, undefined);
    expect(absent.valid).toBe(false);
    expect(absent.reason).toContain("absent");
  });

  it("distingue un cookie expiré d'une signature invalide", async () => {
    const now = Date.now();
    const value = await createSessionValue(secret, now);
    const eightDaysLater = now + 8 * 24 * 60 * 60 * 1000;
    const result = await verifySessionValueVerbose(secret, value, eightDaysLater);
    expect(result.valid).toBe(false);
    expect(result.reason).toContain("expiré");
  });

  it("identifie précisément un SESSION_SECRET différent - le scénario diagnostiqué le 18/08/2026", async () => {
    const now = Date.now();
    const value = await createSessionValue("secret-a", now);
    const result = await verifySessionValueVerbose("secret-b", value, now);
    expect(result.valid).toBe(false);
    expect(result.reason).toContain("signature invalide");
  });

  it("confirme une session valide avec la raison 'ok'", async () => {
    const now = Date.now();
    const value = await createSessionValue(secret, now);
    const result = await verifySessionValueVerbose(secret, value, now + 1000);
    expect(result.valid).toBe(true);
    expect(result.reason).toBe("ok");
  });
});
