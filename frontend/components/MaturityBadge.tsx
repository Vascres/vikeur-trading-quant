const MATURITY_LABELS: Record<string, string> = {
  collecting: "Collecting",
  preliminary: "Preliminary",
  validated: "Validated",
};

const MATURITY_STYLES: Record<string, string> = {
  collecting: "bg-neutral-800 text-neutral-400",
  preliminary: "bg-amber-900/60 text-amber-300",
  validated: "bg-green-900/60 text-green-300",
};

export default function MaturityBadge({ maturity }: { maturity: string | null }) {
  if (!maturity) {
    return <span className="text-neutral-500 text-xs">—</span>;
  }
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-semibold ${MATURITY_STYLES[maturity] ?? "bg-neutral-800 text-neutral-400"}`}
      title="Niveau de maturité de la calibration (Confidence Lifecycle, ADR-0015)"
    >
      {MATURITY_LABELS[maturity] ?? maturity}
    </span>
  );
}
