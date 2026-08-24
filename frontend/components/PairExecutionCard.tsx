import type { PairDecision, PairIncident } from "@/lib/api";

function formatBps(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)} bps`;
}

const RISK_COLORS: Record<string, string> = {
  low: "text-green-400",
  medium: "text-yellow-400",
  high: "text-red-400",
};

export default function PairExecutionCard({
  decisions,
  incidents,
}: {
  decisions: PairDecision[];
  incidents: PairIncident[];
}) {
  const acceptedCount = decisions.filter((d) => d.decision === "accept").length;
  const unresolvedIncidents = incidents.filter((i) => i.realized_cost_bps === null);

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold text-neutral-300 mb-1">
        Pair Execution Engine — Arbitrage de financement (ADR-0021)
      </h2>
      <p className="text-xs text-neutral-500 mb-4">
        {decisions.length} évaluation{decisions.length > 1 ? "s" : ""} récente
        {decisions.length > 1 ? "s" : ""} · {acceptedCount} acceptée{acceptedCount > 1 ? "s" : ""}
      </p>

      {unresolvedIncidents.length > 0 && (
        <div className="mb-4 rounded-md border border-red-500/50 bg-red-500/10 p-3">
          <p className="text-sm font-semibold text-red-400">
            ⚠️ {unresolvedIncidents.length} exécution{unresolvedIncidents.length > 1 ? "s" : ""} partielle
            {unresolvedIncidents.length > 1 ? "s" : ""} non résolue
            {unresolvedIncidents.length > 1 ? "s" : ""}
          </p>
        </div>
      )}

      {decisions.length === 0 ? (
        <p className="text-neutral-400 text-sm">
          Aucune évaluation pour l&apos;instant - le service tourne toutes les 60 secondes, dès qu&apos;un
          taux de financement est mesuré (ADR-0020).
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-neutral-400 text-left border-b border-border">
            <tr>
              <th className="py-2 pr-4">Symbole</th>
              <th className="py-2 pr-4">Funding</th>
              <th className="py-2 pr-4">Edge net</th>
              <th className="py-2 pr-4">Risque exécution</th>
              <th className="py-2 pr-4">Score qualité</th>
              <th className="py-2 pr-4">Décision</th>
              <th className="py-2 pr-4">Statut</th>
              <th className="py-2 pr-4">Heure</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr key={d.id} className="border-b border-border/50">
                <td className="py-2 pr-4 font-medium">{d.symbol}</td>
                <td className="py-2 pr-4">{formatBps(d.funding_rate_bps)}</td>
                <td className={`py-2 pr-4 ${d.net_edge_bps > 0 ? "text-green-400" : "text-red-400"}`}>
                  {formatBps(d.net_edge_bps)}
                </td>
                <td className={`py-2 pr-4 uppercase text-xs ${RISK_COLORS[d.execution_risk] ?? ""}`}>
                  {d.execution_risk}
                </td>
                <td className={`py-2 pr-4 ${d.pair_quality_score > 0 ? "text-green-400" : "text-red-400"}`}>
                  {formatBps(d.pair_quality_score)}
                </td>
                <td className="py-2 pr-4">
                  <span
                    className={
                      d.decision === "accept"
                        ? "rounded bg-green-500/20 px-2 py-0.5 text-green-400 text-xs"
                        : "rounded bg-neutral-700 px-2 py-0.5 text-neutral-400 text-xs"
                    }
                  >
                    {d.decision === "accept" ? "ACCEPT" : "reject"}
                  </span>
                </td>
                <td className="py-2 pr-4 text-neutral-400">{d.status}</td>
                <td className="py-2 pr-4 text-neutral-400 whitespace-nowrap">
                  {new Date(d.created_at).toLocaleString("fr-FR")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
