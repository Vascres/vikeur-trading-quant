import type { WhyNoTradeFunnel } from "@/lib/api";
import { barWidthPercent, costModelClearedPercent, stagesByFamily } from "@/lib/whyNoTrade";

// Les étages "écartés/rejetés/refusées" sont visuellement distincts des
// étages "générés/fusionnées/transmises" (mandat : comprendre en un
// coup d'œil ce qui filtre, pas juste une suite de nombres).
const REJECTION_STAGES = new Set([
  "skipped_regime",
  "no_opinion",
  "excluded_lifecycle",
  "rejected_conviction",
  "rejected_risk_engine",
]);

function FunnelRow({ stage, referenceCount }: { stage: { stage: string; label: string; count: number }; referenceCount: number }) {
  const isRejection = REJECTION_STAGES.has(stage.stage);
  const width = barWidthPercent(stage.count, referenceCount);

  return (
    <div className="py-1.5">
      <div className="flex items-baseline justify-between text-sm">
        <span className={isRejection ? "text-neutral-400" : "text-neutral-200 font-medium"}>{stage.label}</span>
        <span className={isRejection ? "text-red-400" : "text-neutral-200 font-semibold"}>{stage.count}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-neutral-800">
        <div
          className={`h-1.5 rounded-full ${isRejection ? "bg-red-800" : "bg-sky-600"}`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

export default function WhyNoTradeFunnelView({ data }: { data: WhyNoTradeFunnel }) {
  const { engineLevel, decisionLevel } = stagesByFamily(data.funnel);
  const engineReference = engineLevel[0]?.count ?? 0;
  const decisionReference = decisionLevel[0]?.count ?? 0;
  const clearedPct = costModelClearedPercent(data.cost_model_note.cleared, data.cost_model_note.total);

  const ordersExecuted = data.funnel.find((s) => s.stage === "orders_executed")?.count ?? 0;

  return (
    <div className="space-y-6">
      {ordersExecuted === 0 && (
        <div className="rounded-md border border-amber-800 bg-amber-950/40 p-3 text-sm text-amber-300">
          Aucun ordre exécuté sur la période — le système n&apos;est pas cassé, il rejette le bruit du marché
          pour protéger le capital (mandat §21).
        </div>
      )}

      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Niveau moteur — par avis individuel
        </h3>
        <p className="mb-2 text-xs text-neutral-600">
          Un avis par (moteur, symbole, cycle) - jamais directement comparable au niveau décision ci-dessous.
        </p>
        {engineLevel.map((s) => (
          <FunnelRow key={s.stage} stage={s} referenceCount={engineReference} />
        ))}
      </div>

      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Niveau décision — par décision fusionnée
        </h3>
        <p className="mb-2 text-xs text-neutral-600">
          Une décision peut regrouper plusieurs avis moteur survivants (ADR-0010, fusion).
        </p>
        {decisionLevel.map((s) => (
          <FunnelRow key={s.stage} stage={s} referenceCount={decisionReference} />
        ))}
      </div>

      <div className="rounded-md border border-border/60 p-3">
        <div className="flex items-center justify-between text-sm">
          <span className="text-neutral-400">CostModel (observationnel, ne bloque encore aucune décision)</span>
          <span className="text-neutral-300">
            {data.cost_model_note.cleared} / {data.cost_model_note.total}
            {clearedPct !== null && ` (${clearedPct.toFixed(0)}%)`}
          </span>
        </div>
        <p className="mt-1 text-xs text-neutral-600">{data.cost_model_note.note}</p>
      </div>
    </div>
  );
}
