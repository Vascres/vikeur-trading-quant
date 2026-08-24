import Link from "next/link";
import type { Decision } from "@/lib/api";
import MaturityBadge from "@/components/MaturityBadge";

function VerdictBadge({ verdict }: { verdict: string }) {
  const styles: Record<string, string> = {
    signal: "bg-green-900 text-green-300",
    no_signal: "bg-neutral-800 text-neutral-400",
    insufficient_calibration: "bg-neutral-800 text-neutral-400",
  };
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${styles[verdict] ?? "bg-neutral-800 text-neutral-400"}`}>
      {verdict}
    </span>
  );
}

export default function DecisionsTable({ decisions }: { decisions: Decision[] }) {
  if (decisions.length === 0) {
    return <p className="text-neutral-400 text-sm">Aucune décision récente.</p>;
  }

  return (
    <table className="w-full min-w-[880px] text-sm">
      <thead className="text-neutral-400 text-left border-b border-border">
        <tr>
          <th className="py-2 pr-4">Heure</th>
          <th className="py-2 pr-4">Symbole</th>
          <th className="py-2 pr-4">Stratégie</th>
          <th className="py-2 pr-4">Sens</th>
          <th className="py-2 pr-4">Probabilité</th>
          <th className="py-2 pr-4">Calibration</th>
          <th className="py-2 pr-4">Mode</th>
          <th className="py-2 pr-4">Verdict</th>
          <th className="py-2 pr-4">Motif</th>
          <th className="py-2 pr-4" />
        </tr>
      </thead>
      <tbody>
        {decisions.map((d) => (
          <tr key={d.id} className="border-b border-border/50 align-top">
            <td className="py-2 pr-4 text-neutral-400 whitespace-nowrap">
              {new Date(d.time).toLocaleTimeString("fr-FR")}
            </td>
            <td className="py-2 pr-4 font-medium">{d.symbol}</td>
            <td className="py-2 pr-4">{d.strategy_name}</td>
            <td className="py-2 pr-4 uppercase">{d.suggested_side}</td>
            <td className="py-2 pr-4">
              {/* ADR-0014/0015, retour utilisateur du 01/08/2026 : afficher
                  "0.0%" quand aucune probabilite calibree n'existe se lit
                  comme une vraie probabilite nulle, pas comme "indisponible" -
                  on n'affiche le chiffre que si une calibration exploitable
                  existe (preliminary/validated). */}
              {d.calibration_maturity === "preliminary" || d.calibration_maturity === "validated"
                ? `${(d.success_probability * 100).toFixed(1)}%`
                : "—"}
            </td>
            <td className="py-2 pr-4">
              <MaturityBadge maturity={d.calibration_maturity} />
            </td>
            <td className="py-2 pr-4 text-neutral-400">{d.execution_mode ?? "—"}</td>
            <td className="py-2 pr-4">
              <VerdictBadge verdict={d.verdict} />
            </td>
            <td className="py-2 pr-4 text-neutral-400 max-w-xs truncate" title={d.verdict_reason ?? undefined}>
              {d.verdict_reason ?? "—"}
            </td>
            <td className="py-2 pr-4">
              <Link href={`/decisions/${d.id}`} className="text-blue-400 hover:underline whitespace-nowrap">
                Pourquoi ?
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
