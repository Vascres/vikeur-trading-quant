import type { Position } from "@/lib/api";

export default function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return <p className="text-neutral-400 text-sm">Aucune position ouverte.</p>;
  }

  return (
    <table className="w-full min-w-[560px] text-sm">
      <thead className="text-neutral-400 text-left border-b border-border">
        <tr>
          <th className="py-2 pr-4">Symbole</th>
          <th className="py-2 pr-4">Mode</th>
          <th className="py-2 pr-4">Entrée</th>
          <th className="py-2 pr-4">Quantité</th>
          <th className="py-2 pr-4">PnL latent</th>
          <th className="py-2 pr-4">Ouverte le</th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => (
          <tr key={p.id} className="border-b border-border/50">
            <td className="py-2 pr-4 font-medium">{p.symbol}</td>
            <td className="py-2 pr-4 text-neutral-400">{p.execution_mode}</td>
            <td className="py-2 pr-4">{p.entry_price}</td>
            <td className="py-2 pr-4">{p.quantity}</td>
            <td className="py-2 pr-4">{p.unrealized_pnl ?? "—"}</td>
            <td className="py-2 pr-4 text-neutral-400">{new Date(p.opened_at).toLocaleString("fr-FR")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
