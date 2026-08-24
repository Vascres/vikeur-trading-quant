import Link from "next/link";
import { getStrategiesLifecycle, getStrategyPerformanceMetrics } from "@/lib/api";
import type { StrategyPerformanceMetrics } from "@/lib/api";
import { isRatioSampleReliable } from "@/lib/strategyPerformance";
import StrategyDashboardTable from "@/components/StrategyDashboardTable";

export const dynamic = "force-dynamic";

export default async function StrategiesPage({ searchParams }: { searchParams: { mode?: string } }) {
  const executionMode = searchParams.mode === "real" ? "real" : "paper";

  const lifecycle = await getStrategiesLifecycle();

  // Une requête par stratégie, en parallèle - le backend calcule les
  // ratios à partir de l'historique réel (cf. api/main.py::
  // get_strategy_performance_metrics), pas une agrégation qu'on pourrait
  // faire ici sans réimplémenter la même logique d'attribution des
  // trades.
  const metricsEntries = await Promise.all(
    lifecycle.map(
      async (s): Promise<[number, StrategyPerformanceMetrics]> => [
        s.strategy_id,
        await getStrategyPerformanceMetrics(s.strategy_id, executionMode),
      ]
    )
  );
  const metrics = new Map(metricsEntries);

  const minDaysObserved = Math.min(...metricsEntries.map(([, m]) => m.days_observed), Infinity);
  const anyUnreliable = Number.isFinite(minDaysObserved) && !isRatioSampleReliable(minDaysObserved);

  return (
    <main className="min-h-screen bg-background p-4 space-y-6 sm:p-6">
      <div>
        <Link href="/" className="text-xs text-neutral-500 hover:text-neutral-300">
          ← Retour au dashboard
        </Link>
      </div>

      <header>
        <h1 className="text-lg font-semibold sm:text-xl">Stratégies</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Cycle de vie (Étape 3) et ratios de performance financiers, mode {executionMode}.
        </p>
      </header>

      <nav className="flex flex-wrap gap-2 text-xs">
        {["paper", "real"].map((mode) => (
          <Link
            key={mode}
            href={`/strategies?mode=${mode}`}
            className={`rounded-md border px-3 py-1.5 ${
              executionMode === mode
                ? "border-sky-700 bg-sky-950/40 text-sky-300"
                : "border-border bg-surface text-neutral-400 hover:bg-neutral-800"
            }`}
          >
            {mode === "paper" ? "Paper" : "Live (réel)"}
          </Link>
        ))}
      </nav>

      {anyUnreliable && (
        <div className="rounded-md border border-amber-800 bg-amber-950/40 p-3 text-sm text-amber-300">
          Au moins une stratégie a moins de 30 jours observés — ses ratios (grisés ci-dessous) ne sont pas
          encore statistiquement fiables.
        </div>
      )}

      <section className="rounded-lg border border-border bg-surface p-4">
        <div className="-mx-4 overflow-x-auto px-4">
          <StrategyDashboardTable lifecycle={lifecycle} metrics={metrics} />
        </div>
      </section>
    </main>
  );
}
