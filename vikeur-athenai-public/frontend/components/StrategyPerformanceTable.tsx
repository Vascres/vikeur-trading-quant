import type { StrategyPerformance } from "@/lib/api";

export default function StrategyPerformanceTable({ strategies }: { strategies: StrategyPerformance[] }) {
  return (
    <table className="w-full min-w-[480px] text-sm">
      <thead className="text-neutral-400 text-left border-b border-border">
        <tr>
          <th className="py-2 pr-4">Stratégie</th>
          <th className="py-2 pr-4">Statut</th>
          <th className="py-2 pr-4">Allocation recommandée</th>
          <th className="py-2 pr-4">Basé sur (trades)</th>
        </tr>
      </thead>
      <tbody>
        {strategies.map((s) => (
          <tr key={s.name} className="border-b border-border/50">
            <td className="py-2 pr-4 font-medium">{s.name}</td>
            <td className="py-2 pr-4">
              <span
                className={`rounded px-2 py-0.5 text-xs font-semibold ${
                  s.is_active ? "bg-green-900 text-green-300" : "bg-neutral-800 text-neutral-500"
                }`}
              >
                {s.is_active ? "active" : "désactivée"}
              </span>
            </td>
            <td className="py-2 pr-4">
              {s.recommended_fraction !== null ? `${(s.recommended_fraction * 100).toFixed(1)}%` : "—"}
              <span className="text-neutral-500 text-xs"> (recommandation seule, non appliquée - Phase 17 §3)</span>
            </td>
            <td className="py-2 pr-4 text-neutral-400">{s.based_on_trade_count ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
