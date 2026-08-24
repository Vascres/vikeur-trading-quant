import type { PortfolioSummary } from "@/lib/api";

function formatCurrency(value: string | number, currency = "USDT"): string {
  const n = Number(value);
  return `${n.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

export default function PortfolioSummaryCard({ summary }: { summary: PortfolioSummary }) {
  const pnl = Number(summary.total_realized_pnl);
  const pnlIsPositive = pnl > 0;
  const pnlIsZero = pnl === 0;
  const totalClosed = summary.winning_trades + summary.losing_trades;
  const winRate = totalClosed > 0 ? (summary.winning_trades / totalClosed) * 100 : null;

  const pnlColorClass = pnlIsZero
    ? "text-neutral-300"
    : pnlIsPositive
      ? "text-green-400"
      : "text-red-400";

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold text-neutral-300 mb-4">Portefeuille &amp; Performance</h2>

      {/* Fonds réels par exchange */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-5">
        {summary.balances.length === 0 && (
          <p className="text-neutral-400 text-sm col-span-2">Aucun relevé de portefeuille disponible.</p>
        )}
        {summary.balances.map((b) => (
          <div key={`${b.exchange}-${b.market_type ?? "spot"}`} className="rounded-md border border-border/60 p-3">
            <div className="text-xs text-neutral-500 uppercase mb-1">
              Solde réel — {b.exchange} ({b.market_type === "futures_perpetual" ? "futures" : "spot"})
            </div>
            <div className="text-2xl font-semibold">
              {formatCurrency(b.total_value_reference_currency, b.reference_currency)}
            </div>
            <div className="text-xs text-neutral-500 mt-1">
              Relevé le {new Date(b.taken_at).toLocaleString("fr-FR")}
            </div>
          </div>
        ))}
      </div>

      {/* Bilan gains/pertes */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-border/60">
        <div>
          <div className="text-xs text-neutral-500">PnL réalisé cumulé</div>
          <div className={`text-lg font-semibold ${pnlColorClass}`}>
            {pnlIsPositive ? "+" : ""}
            {formatCurrency(pnl)}
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500">Taux de réussite</div>
          <div className="text-lg font-semibold">{winRate !== null ? `${winRate.toFixed(0)}%` : "—"}</div>
          <div className="text-xs text-neutral-500 mt-0.5">
            {summary.winning_trades} gagnants / {summary.losing_trades} perdants
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500">Trades clôturés</div>
          <div className="text-lg font-semibold">{summary.closed_trades}</div>
        </div>
        <div>
          <div className="text-xs text-neutral-500">Trades ouverts</div>
          <div className="text-lg font-semibold">{summary.open_trades}</div>
        </div>
      </div>

      {totalClosed < 30 && (
        <p className="text-xs text-neutral-500 mt-4 border-t border-border/60 pt-3">
          Échantillon encore faible ({totalClosed} trade{totalClosed > 1 ? "s" : ""} clôturé
          {totalClosed > 1 ? "s" : ""}) — ces statistiques ne sont pas encore statistiquement fiables
          (cf. Confidence Lifecycle, ADR-0015 : validation à partir de 30 trades).
        </p>
      )}
    </div>
  );
}
