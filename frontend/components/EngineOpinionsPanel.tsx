import type { EngineOpinion } from "@/lib/api";

function ScoreBar({ value, max = 1 }: { value: number; max?: number }) {
  const percent = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="h-1.5 w-full rounded-full bg-neutral-800 overflow-hidden">
      <div className="h-full rounded-full bg-blue-500" style={{ width: `${percent}%` }} />
    </div>
  );
}

export default function EngineOpinionsPanel({ opinions }: { opinions: EngineOpinion[] }) {
  if (opinions.length === 0) {
    return <p className="text-neutral-400 text-sm">Aucun moteur n&apos;a produit d&apos;avis pour cette décision.</p>;
  }

  return (
    <div className="space-y-4">
      {opinions.map((opinion) => (
        <div key={opinion.id} className="rounded-md border border-border/60 p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="font-medium text-sm">{opinion.engine_name}</span>
            <span
              className={`text-xs font-semibold uppercase ${
                opinion.suggested_side === "buy" ? "text-green-400" : "text-red-400"
              }`}
            >
              {opinion.suggested_side}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs text-neutral-400 mb-3">
            <div>
              <div className="flex justify-between mb-1">
                <span>Score</span>
                <span className="text-neutral-200">{opinion.score.toFixed(2)}</span>
              </div>
              <ScoreBar value={opinion.score} />
            </div>
            <div>
              <div className="flex justify-between mb-1">
                <span>Confiance</span>
                <span className="text-neutral-200">{opinion.confidence.toFixed(2)}</span>
              </div>
              <ScoreBar value={opinion.confidence} />
            </div>
          </div>

          <div className="text-xs text-neutral-500 mb-2">
            Incertitude : <span className="text-neutral-300">{opinion.uncertainty.toFixed(4)}</span>
          </div>

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-400">
            {Object.entries(opinion.rationale).map(([key, value]) => (
              <span key={key}>
                {key} : <span className="text-neutral-200">{typeof value === "number" ? value.toFixed(4) : String(value)}</span>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
