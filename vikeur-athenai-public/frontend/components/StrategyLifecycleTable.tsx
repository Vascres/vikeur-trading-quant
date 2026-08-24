import type { StrategyLifecycle } from "@/lib/api";
import { lifecycleStatusIsEvictionPath, lifecycleStatusLabel, lifecycleStatusStyle } from "@/lib/strategyLifecycle";

function formatBps(value: number | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)} bps`;
}

function formatPnl(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

export default function StrategyLifecycleTable({ strategies }: { strategies: StrategyLifecycle[] }) {
  if (strategies.length === 0) {
    return <p className="text-sm text-neutral-500">Aucune stratégie active.</p>;
  }

  return (
    <table className="w-full min-w-[600px] text-sm">
      <thead className="text-neutral-400 text-left border-b border-border">
        <tr>
          <th className="py-2 pr-4">Stratégie</th>
          <th className="py-2 pr-4">Statut</th>
          <th className="py-2 pr-4">Espérance nette</th>
          <th className="py-2 pr-4">P&amp;L cumulé</th>
          <th className="py-2 pr-4">Profit factor</th>
          <th className="py-2 pr-4">Échantillon</th>
        </tr>
      </thead>
      <tbody>
        {strategies.map((s) => {
          const evPositive = s.ev_net_bps !== null && s.ev_net_bps > 0;
          const evNegative = s.ev_net_bps !== null && s.ev_net_bps < 0;
          const showReason = lifecycleStatusIsEvictionPath(s.status) && s.reason;

          return (
            <tr key={s.strategy_id} className="border-b border-border/50 align-top">
              <td className="py-2 pr-4 font-medium">{s.name}</td>
              <td className="py-2 pr-4">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-semibold ${lifecycleStatusStyle(s.status)}`}
                  title="Strategy Lifecycle (Étape 3)"
                >
                  {lifecycleStatusLabel(s.status)}
                </span>
                {showReason && <p className="mt-1 text-xs text-neutral-500 max-w-xs">{s.reason}</p>}
              </td>
              <td
                className={`py-2 pr-4 ${evPositive ? "text-green-400" : evNegative ? "text-red-400" : "text-neutral-400"}`}
              >
                {formatBps(s.ev_net_bps)}
              </td>
              <td className="py-2 pr-4 text-neutral-300">{formatPnl(s.cumulative_pnl_reference_currency)}</td>
              <td className="py-2 pr-4 text-neutral-300">
                {s.profit_factor !== null ? s.profit_factor.toFixed(2) : "—"}
              </td>
              <td className="py-2 pr-4 text-neutral-400">{s.sample_size ?? "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
