import type { StrategyLifecycle, StrategyPerformanceMetrics } from "@/lib/api";
import { lifecycleStatusLabel, lifecycleStatusStyle } from "@/lib/strategyLifecycle";
import { formatDrawdownPct, formatRatio, isRatioSampleReliable } from "@/lib/strategyPerformance";

// Mandat §14 ("Dashboard des Stratégies") - une ligne par stratégie
// combinant deux sources distinctes (jointes ici, jamais fusionnées côté
// backend, cf. api/main.py) : le statut Strategy Lifecycle (Étape 3) et
// les ratios de performance financiers (Sharpe/Sortino/Calmar,
// 16/08/2026). Les deux se recalculent séparément et n'ont aucune
// raison de partager une même requête.
export default function StrategyDashboardTable({
  lifecycle,
  metrics,
}: {
  lifecycle: StrategyLifecycle[];
  metrics: Map<number, StrategyPerformanceMetrics>;
}) {
  if (lifecycle.length === 0) {
    return <p className="text-sm text-neutral-500">Aucune stratégie active.</p>;
  }

  return (
    <table className="w-full min-w-[640px] text-sm">
      <thead className="text-neutral-400 text-left border-b border-border">
        <tr>
          <th className="py-2 pr-4">Stratégie</th>
          <th className="py-2 pr-4">Statut</th>
          <th className="py-2 pr-4">Trades</th>
          <th className="py-2 pr-4">Sharpe</th>
          <th className="py-2 pr-4">Sortino</th>
          <th className="py-2 pr-4">Calmar</th>
          <th className="py-2 pr-4">Max Drawdown</th>
        </tr>
      </thead>
      <tbody>
        {lifecycle.map((s) => {
          const m = metrics.get(s.strategy_id);
          const reliable = m ? isRatioSampleReliable(m.days_observed) : false;
          const ratioClass = reliable ? "text-neutral-200" : "text-neutral-600";

          return (
            <tr key={s.strategy_id} className="border-b border-border/50 align-top">
              <td className="py-2 pr-4 font-medium">{s.name}</td>
              <td className="py-2 pr-4">
                <span className={`rounded px-2 py-0.5 text-xs font-semibold ${lifecycleStatusStyle(s.status)}`}>
                  {lifecycleStatusLabel(s.status)}
                </span>
              </td>
              <td className="py-2 pr-4 text-neutral-400">{m?.trade_count ?? "—"}</td>
              <td className={`py-2 pr-4 ${ratioClass}`}>{formatRatio(m?.sharpe_ratio ?? null)}</td>
              <td className={`py-2 pr-4 ${ratioClass}`}>{formatRatio(m?.sortino_ratio ?? null)}</td>
              <td className={`py-2 pr-4 ${ratioClass}`}>{formatRatio(m?.calmar_ratio ?? null)}</td>
              <td className={`py-2 pr-4 ${ratioClass}`}>{formatDrawdownPct(m?.max_drawdown_pct ?? null)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
