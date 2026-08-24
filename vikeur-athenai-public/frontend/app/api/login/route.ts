import { scryptSync, timingSafeEqual } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME, createSessionValue } from "@/lib/session";

const SESSION_SECRET = process.env.SESSION_SECRET ?? "";
const DASHBOARD_PASSWORD_HASH = process.env.DASHBOARD_PASSWORD_HASH ?? "";

/** Format attendu du hash : "salt:hash" (hexadécimal), généré par le script
 * fourni (Module 1, §7). Comparaison en temps constant. */
function verifyPassword(password: string, storedHash: string): boolean {
  const [salt, hash] = storedHash.split(":");
  if (!salt || !hash) return false;

  const derived = scryptSync(password, salt, 64);
  const expected = Buffer.from(hash, "hex");
  if (derived.length !== expected.length) return false;

  return timingSafeEqual(derived, expected);
}

export async function POST(request: NextRequest) {
  const { password } = await request.json();

  if (!DASHBOARD_PASSWORD_HASH || !verifyPassword(password ?? "", DASHBOARD_PASSWORD_HASH)) {
    return NextResponse.json({ error: "Mot de passe incorrect." }, { status: 401 });
  }

  const sessionValue = await createSessionValue(SESSION_SECRET);
  const response = NextResponse.json({ success: true });
  response.cookies.set(SESSION_COOKIE_NAME, sessionValue, {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
  });
  return response;
}
