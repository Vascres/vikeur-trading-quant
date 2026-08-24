import type { RiskCheck } from "@/lib/api";

export default function RiskChecksPanel({ checks }: { checks: RiskCheck[] }) {
  if (checks.length === 0) {
    return (
      <p className="text-neutral-400 text-sm">
        Aucune vérification Risk Engine enregistrée - la décision n&apos;a jamais atteint cette étape
        (verdict non &apos;signal&apos;, cf. Meta Engine ci-dessus).
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {checks.map((check) => (
        <li
          key={check.rule_name}
          className="flex items-start justify-between gap-4 rounded-md border border-border/60 px-3 py-2 text-sm"
        >
          <span className="text-neutral-300">{check.rule_name}</span>
          <span className={`text-right ${check.passed ? "text-green-400" : "text-red-400"}`}>
            {check.passed ? "OK" : (check.reason ?? "Refusé")}
          </span>
        </li>
      ))}
    </ul>
  );
}
