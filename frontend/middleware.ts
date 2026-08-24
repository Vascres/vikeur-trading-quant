import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME, verifySessionValue } from "@/lib/session";

const SESSION_SECRET = process.env.SESSION_SECRET ?? "";

export async function middleware(request: NextRequest) {
  const cookie = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  const isValid = await verifySessionValue(SESSION_SECRET, cookie);

  if (!isValid) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

// Toutes les pages, sauf /login et les routes /api/* (qui vérifient leur
// propre session et répondent en JSON 401 plutôt que par une redirection
// HTML - Module 1, §5), et les ressources statiques.
export const config = {
  matcher: ["/((?!login|api|_next/static|_next/image|favicon.ico).*)"],
};
