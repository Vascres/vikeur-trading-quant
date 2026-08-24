import Link from "next/link";
import { getWhyNoTrade } from "@/lib/api";
import WhyNoTradeFunnelView from "@/components/WhyNoTradeFunnelView";

export const dynamic = "force-dynamic";

export default async function WhyNoTradePage({
  searchParams,
}: {
  searchParams: { mode?: string; hours?: string };
}) {
  const executionMode = searchParams.mode === "real" ? "real" : "paper";
  const sinceHours = Number(searchParams.hours) > 0 ? Number(searchParams.hours) : 24;

  const data = await getWhyNoTrade(executionMode, sinceHours);

  return (
    <main className="min-h-screen bg-background p-4 space-y-6 sm:p-6">
      <div>
        <Link href="/" className="text-xs text-neutral-500 hover:text-neutral-300">
          ← Retour au dashboard
        </Link>
      </div>

      <header>
        <h1 className="text-lg font-semibold sm:text-xl">Why No Trade ?</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Pourquoi Vikeur n&apos;a (ou n&apos;a pas) tradé sur les dernières {sinceHours}h — mode {executionMode}.
        </p>
      </header>

      <nav className="flex flex-wrap gap-2 text-xs">
        {["paper", "real"].map((mode) => (
          <Link
            key={mode}
            href={`/why-no-trade?mode=${mode}&hours=${sinceHours}`}
            className={`rounded-md border px-3 py-1.5 ${
              executionMode === mode
                ? "border-sky-700 bg-sky-950/40 text-sky-300"
                : "border-border bg-surface text-neutral-400 hover:bg-neutral-800"
            }`}
          >
            {mode === "paper" ? "Paper" : "Live (réel)"}
          </Link>
        ))}
        {[24, 48, 168].map((hours) => (
          <Link
            key={hours}
            href={`/why-no-trade?mode=${executionMode}&hours=${hours}`}
            className={`rounded-md border px-3 py-1.5 ${
              sinceHours === hours
                ? "border-sky-700 bg-sky-950/40 text-sky-300"
                : "border-border bg-surface text-neutral-400 hover:bg-neutral-800"
            }`}
          >
            {hours}h
          </Link>
        ))}
      </nav>

      <section className="rounded-lg border border-border bg-surface p-4">
        <WhyNoTradeFunnelView data={data} />
      </section>
    </main>
  );
}
