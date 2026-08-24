import Link from "next/link";
import type { Position } from "@/lib/api";

function formatNumber(value: string | null): string {
  if (value === null) return "—";
  return Number(value).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

export default function TradeHistoryTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return <p className="text-neutral-400 text-sm">Aucun trade clôturé pour l&apos;instant.</p>;
  }

  return (
    <table className="w-full min-w-[760px] text-sm">
      <thead className="text-neutral-400 text-left border-b border-border">
        <tr>
          <th className="py-2 pr-4">Symbole</th>
          <th className="py-2 pr-4">Marché</th>
          <th className="py-2 pr-4">Entrée</th>
          <th className="py-2 pr-4">Sortie</th>
          <th className="py-2 pr-4">Quantité</th>
          <th className="py-2 pr-4">PnL réalisé</th>
          <th className="py-2 pr-4">Ouverte le</th>
          <th className="py-2 pr-4">Clôturée le</th>
          <th className="py-2 pr-4" />
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => {
          const pnl = p.realized_pnl !== null ? Number(p.realized_pnl) : null;
          const pnlColorClass =
            pnl === null ? "text-neutral-400" : pnl > 0 ? "text-green-400" : pnl < 0 ? "text-red-400" : "text-neutral-300";
          const marketLabel =
            p.market_type === "futures_perpetual"
              ? `Futures${p.position_side ? ` (${p.position_side === "long" ? "long" : "court"})` : ""}`
              : "Spot";

          return (
            <tr key={p.id} className="border-b border-border/50">
              <td className="py-2 pr-4 font-medium">{p.symbol}</td>
              <td className="py-2 pr-4 text-neutral-400">{marketLabel}</td>
              <td className="py-2 pr-4">{formatNumber(p.entry_price)}</td>
              <td className="py-2 pr-4">{formatNumber(p.exit_price)}</td>
              <td className="py-2 pr-4">{formatNumber(p.quantity)}</td>
              <td className={`py-2 pr-4 font-semibold ${pnlColorClass}`}>
                {pnl !== null ? `${pnl > 0 ? "+" : ""}${pnl.toFixed(4)}` : "—"}
              </td>
              <td className="py-2 pr-4 text-neutral-400 whitespace-nowrap">
                {new Date(p.opened_at).toLocaleString("fr-FR")}
              </td>
              <td className="py-2 pr-4 text-neutral-400 whitespace-nowrap">
                {p.closed_at ? new Date(p.closed_at).toLocaleString("fr-FR") : "—"}
              </td>
              <td className="py-2 pr-4">
                {p.decision_id !== null ? (
                  <Link href={`/decisions/${p.decision_id}`} className="text-blue-400 hover:underline whitespace-nowrap">
                    Pourquoi ?
                  </Link>
                ) : (
                  <span className="text-neutral-600 text-xs">décision inconnue</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
