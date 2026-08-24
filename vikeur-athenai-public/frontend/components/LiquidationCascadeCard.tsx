import type { LiquidationCascadeOpinion } from "@/lib/api";

function formatUsd(value: number | null): string {
  if (value === null) return "—";
  return `${value.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} $`;
}

function formatPct(value: number | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

// Remplace la carte Pair Execution Engine sur le dashboard (17/08/2026,
// demande frontend) - `pair_execution` reste hors fusion et documenté
// comme sans mécanisme de sortie (audit initial, toujours vrai), tandis
// que `liquidation_cascade` est le moteur futures réellement actif
// depuis ce soir (câblé au routage par market_type). L'ancienne carte
// et ses données restent disponibles côté API (`/pair-decisions`,
// `/pair-incidents`) - rien n'est supprimé, seul l'espace du dashboard
// principal change de priorité.
export default function LiquidationCascadeCard({ opinions }: { opinions: LiquidationCascadeOpinion[] }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <h2 className="mb-1 text-sm font-semibold text-neutral-300">
        Liquidation Cascade Engine — Mean-reversion futures (16/08/2026)
      </h2>
      <p className="mb-4 text-xs text-neutral-500">
        {opinions.length} avis récent{opinions.length > 1 ? "s" : ""} · seuils de départ, non calibrés
        empiriquement — la collecte de liquidations vient de démarrer.
      </p>

      {opinions.length === 0 ? (
        <p className="text-sm text-neutral-400">
          Aucun avis pour l&apos;instant — le moteur ne se déclenche que si une intensité de liquidation ET
          un mouvement de prix notables sont détectés simultanément. Le silence est le comportement normal
          tant qu&apos;aucune cascade réelle ne survient.
        </p>
      ) : (
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b border-border text-left text-neutral-400">
              <tr>
                <th className="py-2 pr-4">Symbole</th>
                <th className="py-2 pr-4">Sens</th>
                <th className="py-2 pr-4">Notionnel liquidé</th>
                <th className="py-2 pr-4">Momentum</th>
                <th className="py-2 pr-4">Spread</th>
                <th className="py-2 pr-4">Score</th>
                <th className="py-2 pr-4">Heure</th>
              </tr>
            </thead>
            <tbody>
              {opinions.map((o) => (
                <tr key={o.id} className="border-b border-border/50">
                  <td className="py-2 pr-4 font-medium">{o.symbol}</td>
                  <td className="py-2 pr-4">
                    <span
                      className={
                        o.suggested_side === "buy"
                          ? "rounded bg-green-500/20 px-2 py-0.5 text-xs text-green-400"
                          : "rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-400"
                      }
                    >
                      {o.suggested_side.toUpperCase()}
                    </span>
                  </td>
                  <td className="py-2 pr-4">{formatUsd(o.liquidation_notional_usd)}</td>
                  <td className={`py-2 pr-4 ${(o.momentum ?? 0) < 0 ? "text-red-400" : "text-green-400"}`}>
                    {formatPct(o.momentum)}
                  </td>
                  <td className="py-2 pr-4 text-neutral-400">
                    {o.spread_bps !== null ? `${o.spread_bps.toFixed(1)} bps` : "—"}
                  </td>
                  <td className="py-2 pr-4 text-neutral-300">{o.score.toFixed(2)}</td>
                  <td className="py-2 pr-4 whitespace-nowrap text-neutral-400">
                    {new Date(o.time).toLocaleString("fr-FR")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
