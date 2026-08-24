/**
 * Signature/vérification de session (Module 1, §5).
 * Fonctions pures, utilisent Web Crypto (disponible en runtime Node et Edge,
 * donc utilisables aussi bien dans middleware.ts que dans les routes API).
 */

export const SESSION_COOKIE_NAME = "session";
const SESSION_DURATION_MS = 7 * 24 * 60 * 60 * 1000; // 7 jours

async function hmac(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(signature))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Crée une valeur de cookie signée "expiresAt.signature" (Module 1, §5). */
export async function createSessionValue(secret: string, now: number = Date.now()): Promise<string> {
  const expiresAt = now + SESSION_DURATION_MS;
  const signature = await hmac(secret, String(expiresAt));
  return `${expiresAt}.${signature}`;
}

/** Vérifie qu'une valeur de cookie est valide (signature correcte, non expirée). */
export async function verifySessionValue(
  secret: string,
  cookieValue: string | undefined,
  now: number = Date.now()
): Promise<boolean> {
  const result = await verifySessionValueVerbose(secret, cookieValue, now);
  return result.valid;
}

/** Même vérification, mais indique la raison précise d'un refus - ajouté
 * le 18/08/2026 pour diagnostiquer un cas où la navigation entre pages
 * fonctionnait (middleware.ts) mais les actions POST échouaient
 * (routes /api/*) avec "Non authentifié.", sans qu'on sache si c'était
 * un cookie absent, expiré, ou un SESSION_SECRET différent entre le
 * runtime Edge (middleware) et le runtime Node (route handlers) - un
 * écart possible en particulier avec la sortie `standalone` de Next.js. */
export async function verifySessionValueVerbose(
  secret: string,
  cookieValue: string | undefined,
  now: number = Date.now()
): Promise<{ valid: boolean; reason: string }> {
  if (!cookieValue) return { valid: false, reason: "cookie absent de la requête" };

  const [expiresAtRaw, signature] = cookieValue.split(".");
  if (!expiresAtRaw || !signature) return { valid: false, reason: "format de cookie invalide" };

  const expiresAt = Number(expiresAtRaw);
  if (!Number.isFinite(expiresAt) || expiresAt < now) return { valid: false, reason: "cookie expiré" };

  const expectedSignature = await hmac(secret, expiresAtRaw);
  const sigMatches = timingSafeEqual(signature, expectedSignature);
  return {
    valid: sigMatches,
    reason: sigMatches ? "ok" : "signature invalide (SESSION_SECRET différent de celui utilisé à la connexion ?)",
  };
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}
