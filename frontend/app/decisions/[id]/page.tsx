import Link from "next/link";
import { getDecisionExplanation } from "@/lib/api";
import type { RiskCheck } from "@/lib/api";
import MaturityBadge from "@/components/MaturityBadge";
import EngineOpinionsPanel from "@/components/EngineOpinionsPanel";
import RiskChecksPanel from "@/components/RiskChecksPanel";

export const dynamic = "force-dynamic";

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-neutral-300">{title}</h2>
        {subtitle && <p className="text-xs text-neutral-500 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function Metric({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div>
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
      {hint && <div className="text-xs text-neutral-500 mt-0.5">{hint}</div>}
    </div>
  );
}

function VerdictHeadline({ verdict, riskChecks }: { verdict: string; riskChecks: RiskCheck[] }) {
  // ADR-0014/0015 : `decision.verdict === 'signal'` signifie seulement que
  // decision_engine a autorisé le franchissement du seuil (bootstrap ou
  // calibré) - ça ne veut PAS dire que la position a réellement été
  // ouverte. Le Risk Engine peut encore refuser derrière (Phase 13) ;
  // avant ce correctif, ce bandeau ignorait `risk_checks` et affichait
  // "OPEN POSITION" même quand le Risk Engine avait explicitement rejeté
  // la décision - corrigé suite au retour utilisateur du 01/08/2026.
  if (verdict !== "signal") {
    const label = verdict === "no_signal" ? "NO SIGNAL" : "NO SIGNAL — CALIBRATION INSUFFISANTE";
    return (
      <div className="rounded-md border px-4 py-3 text-center font-semibold bg-neutral-800 text-neutral-300 border-neutral-700">
        {label}
      </div>
    );
  }

  if (riskChecks.length === 0) {
    return (
      <div className="rounded-md border px-4 py-3 text-center font-semibold bg-amber-900/40 text-amber-300 border-amber-800">
        SIGNAL ÉMIS — EN ATTENTE DU RISK ENGINE
      </div>
    );
  }

  const failedChecks = riskChecks.filter((c) => !c.passed);
  if (failedChecks.length > 0) {
    return (
      <div className="space-y-2">
        <div className="rounded-md border px-4 py-3 text-center font-semibold bg-red-900/40 text-red-300 border-red-800">
          REFUSÉ PAR LE RISK ENGINE
        </div>
        <ul className="text-sm text-neutral-400 space-y-1">
          {failedChecks.map((c) => (
            <li key={c.rule_name}>
              <span className="text-neutral-300">{c.rule_name}</span> : {c.reason ?? "refusé"}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="rounded-md border px-4 py-3 text-center font-semibold bg-green-900/60 text-green-300 border-green-800">
      OPEN POSITION
    </div>
  );
}

export default async function DecisionExplainPage({ params }: { params: { id: string } }) {
  const decisionId = Number(params.id);
  const explanation = await getDecisionExplanation(decisionId);
  const { decision, meta_decision, contributing_opinions, risk_checks, calibration } = explanation;

  return (
    <main className="min-h-screen bg-background p-4 space-y-6 sm:p-6">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Link href="/" className="text-xs text-neutral-500 hover:text-neutral-300">
            ← Retour au tableau de bord
          </Link>
          <h1 className="text-lg font-semibold mt-1 sm:text-xl">
            {decision.symbol} — Décision #{decision.id}
          </h1>
          <p className="text-xs text-neutral-500 mt-1">
            {new Date(decision.time).toLocaleString("fr-FR")} · {decision.exchange}
          </p>
        </div>
        <span className={`text-lg font-bold uppercase ${decision.suggested_side === "buy" ? "text-green-400" : "text-red-400"}`}>
          {decision.suggested_side}
        </span>
      </header>

      {/* --- Meta Engine --- */}
      <Section title="Meta Engine" subtitle="Fusion pondérée par la confiance des moteurs contributeurs (ADR-0010)">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          <Metric label="Score fusionné" value={meta_decision?.fused_score?.toFixed(2) ?? "—"} />
          <Metric label="Méthode" value={meta_decision?.fusion_method ?? "—"} />
          <Metric
            label="Régime de marché"
            value={meta_decision?.regime_type ?? "unknown"}
            hint={
              meta_decision?.regime_confidence != null
                ? `confiance ${(meta_decision.regime_confidence * 100).toFixed(0)}%`
                : undefined
            }
          />
          <div>
            <div className="text-xs text-neutral-500">Poids appliqués</div>
            <div className="text-sm mt-1 space-y-0.5">
              {meta_decision && Object.keys(meta_decision.weights_applied).length > 0
                ? Object.entries(meta_decision.weights_applied).map(([name, weight]) => (
                    <div key={name} className="text-neutral-300">
                      {name} : {weight.toFixed(2)}
                    </div>
                  ))
                : "—"}
            </div>
          </div>
        </div>
        <h3 className="text-xs font-semibold text-neutral-400 mb-2 uppercase">Moteurs contributeurs</h3>
        <EngineOpinionsPanel opinions={contributing_opinions} />
      </Section>

      {/* --- Calibration --- */}
      <Section title="Calibration" subtitle="Confidence Lifecycle (ADR-0015) — collecting → preliminary → validated">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-xs text-neutral-500 mb-1">Niveau de maturité</div>
            <MaturityBadge maturity={meta_decision?.calibration_maturity ?? null} />
          </div>
          {meta_decision?.success_probability != null ? (
            <Metric
              label="Probabilité calibrée"
              value={`${(meta_decision.success_probability * 100).toFixed(1)}%`}
              hint={meta_decision.calibration_maturity === "preliminary" ? "préliminaire, non validée" : undefined}
            />
          ) : (
            <Metric
              label="Probabilité calibrée"
              value="Non disponible"
              hint={`Trades observés : ${explanation.calibration_progress.trades_observed} / ${explanation.calibration_progress.minimum_for_validated}`}
            />
          )}
          <Metric label="Méthode" value={calibration?.method ?? "—"} />
          <Metric
            label="Échantillon"
            value={calibration ? `${calibration.sample_size}` : `${explanation.calibration_progress.trades_observed}`}
            hint={calibration ? (calibration.is_validated ? "validée" : "non validée") : "aucune calibration persistée"}
          />
        </div>
        {meta_decision?.verdict_reason && (
          <p className="text-sm text-neutral-400 mt-4 border-t border-border/60 pt-3">
            {meta_decision.verdict_reason}
          </p>
        )}
      </Section>

      {/* --- Coûts / espérance --- */}
      <Section title="Coûts d'exécution & espérance" subtitle="meta_engine/cost_estimation.py (ADR-0010)">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <Metric label="Espérance calculée" value={`${(decision.expected_value * 100).toFixed(3)}%`} />
          <Metric label="Ratio rendement/risque" value={decision.risk_reward_ratio.toFixed(2)} />
          <Metric
            label="Probabilité (decisions)"
            value={
              meta_decision?.calibration_maturity === "validated" || meta_decision?.calibration_maturity === "preliminary"
                ? `${(decision.success_probability * 100).toFixed(1)}%`
                : "Non disponible"
            }
          />
        </div>
      </Section>

      {/* --- Risk Engine --- */}
      <Section title="Risk Engine" subtitle="Vérifications appliquées avant exécution (Phase 13)">
        <RiskChecksPanel checks={risk_checks} />
      </Section>

      {/* --- Verdict final --- */}
      <Section title="Décision finale">
        <VerdictHeadline verdict={decision.verdict} riskChecks={risk_checks} />
      </Section>
    </main>
  );
}
