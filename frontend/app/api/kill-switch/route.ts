import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME, verifySessionValueVerbose } from "@/lib/session";

// Correctif du 18/08/2026 : appel serveur-a-serveur, TOUJOURS
// vers l'hote interne Docker, jamais PUBLIC_API_URL - si celle-ci
// pointe vers https://vikeur.com/api (cas normal en production),
// cet appel POST ressortirait sur Internet et repasserait par
// Caddy, qui route tout POST sur ce meme chemin vers CE conteneur
// frontend (regle @frontend_mutations, cf. Caddyfile) - la route
// s'appelait donc elle-meme en boucle au lieu d'atteindre le vrai
// backend, jusqu'a echouer en 502 (bug reel trouve le 18/08/2026).
const API_URL = "http://backend:8000";
const API_AUTH_TOKEN = process.env.API_AUTH_TOKEN ?? "";
const SESSION_SECRET = process.env.SESSION_SECRET ?? "";

async function requireSession(request: NextRequest): Promise<boolean> {
  const cookie = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  const result = await verifySessionValueVerbose(SESSION_SECRET, cookie);
  if (!result.valid) {
    // Diagnostic temporaire du 18/08/2026 - cf. paper-capital/route.ts.
    console.error(`[kill-switch] Session refusée : ${result.reason}`);
  }
  return result.valid;
}

export async function GET(request: NextRequest) {
  if (!(await requireSession(request))) {
    return NextResponse.json({ error: "Non authentifié." }, { status: 401 });
  }

  const response = await fetch(`${API_URL}/kill-switch`, {
    headers: { Authorization: `Bearer ${API_AUTH_TOKEN}` },
    cache: "no-store",
  });
  return NextResponse.json(await response.json(), { status: response.status });
}

export async function POST(request: NextRequest) {
  if (!(await requireSession(request))) {
    return NextResponse.json({ error: "Non authentifié." }, { status: 401 });
  }

  const body = await request.json();

  const response = await fetch(`${API_URL}/kill-switch`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${API_AUTH_TOKEN}`,
    },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await response.json(), { status: response.status });
}
