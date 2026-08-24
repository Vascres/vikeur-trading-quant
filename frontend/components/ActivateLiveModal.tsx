"use client";

import type { GovernanceCheckResult } from "@/lib/api";

// Mandat §10 : "Le bouton LIVE doit être extrêmement sécurisé... une
// modale agressive (rouge)" - remplace l'ancien window.confirm()
// natif (non stylé, facilement ignoré) par un composant dédié qui
// affiche explicitement chaque prérequis avant même de proposer la
// phrase de confirmation. Le frontend ne peut jamais contourner la
// gouvernance réelle (celle-ci vit côté backend,
// execution_mode_governance) - ce composant est de l'UX, pas la
// protection elle-même.
export default function ActivateLiveModal({
  confirmationPhrase,
  prerequisites,
  requestedBy,
  confirmationInput,
  onRequestedByChange,
  onConfirmationInputChange,
  onConfirm,
  onCancel,
  pending,
  error,
}: {
  confirmationPhrase: string;
  prerequisites: GovernanceCheckResult[];
  requestedBy: string;
  confirmationInput: string;
  onRequestedByChange: (value: string) => void;
  onConfirmationInputChange: (value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  pending: boolean;
  error: string | null;
}) {
  const allPrerequisitesPassed = prerequisites.length > 0 && prerequisites.every((p) => p.passed);
  const phraseMatches = confirmationInput === confirmationPhrase;
  const canConfirm = allPrerequisitesPassed && phraseMatches && requestedBy.trim().length > 0 && !pending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
      <div className="w-full max-w-lg rounded-lg border-2 border-red-700 bg-neutral-950 shadow-[0_0_40px_rgba(220,38,38,0.35)]">
        <div className="border-b-2 border-red-800 bg-red-950/50 px-5 py-4">
          <h2 className="text-lg font-bold text-red-400">⚠️ ACTIVATION DU MODE RÉEL</h2>
          <p className="mt-1 text-sm text-red-300/80">
            Le capital réel sera engagé. Cette action est irréversible sans repasser explicitement en Paper.
          </p>
        </div>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto px-5 py-4">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Prérequis de gouvernance
            </h3>
            {prerequisites.length === 0 ? (
              <p className="text-sm text-neutral-500">Aucun prérequis chargé.</p>
            ) : (
              <ul className="space-y-1.5">
                {prerequisites.map((p) => (
                  <li
                    key={p.check}
                    className={`flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-sm ${
                      p.passed ? "border-green-900 bg-green-950/30" : "border-red-900 bg-red-950/30"
                    }`}
                  >
                    <span className="text-neutral-300">{p.check}</span>
                    <span className={p.passed ? "text-green-400" : "text-right text-red-400"}>
                      {p.passed ? "✓" : (p.reason ?? "Non satisfait")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {!allPrerequisitesPassed && prerequisites.length > 0 && (
              <p className="mt-2 text-sm font-semibold text-red-400">
                Au moins un prérequis n&apos;est pas satisfait — le backend refusera cette demande quelle que
                soit ta saisie ci-dessous.
              </p>
            )}
          </div>

          <div className="space-y-2 border-t border-border pt-3">
            <label className="block text-xs text-neutral-500">Ton nom (traçabilité, ADR-0008)</label>
            <input
              value={requestedBy}
              onChange={(e) => onRequestedByChange(e.target.value)}
              placeholder="Opérateur"
              className="w-full rounded-md border border-border bg-neutral-900 px-3 py-1.5 text-sm"
            />

            <label className="block text-xs text-neutral-500">
              Saisir exactement « {confirmationPhrase} » pour confirmer
            </label>
            <input
              value={confirmationInput}
              onChange={(e) => onConfirmationInputChange(e.target.value)}
              className={`w-full rounded-md border bg-neutral-900 px-3 py-1.5 text-sm ${
                confirmationInput.length === 0
                  ? "border-border"
                  : phraseMatches
                    ? "border-green-700"
                    : "border-red-700"
              }`}
            />
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>

        <div className="flex gap-3 border-t border-border px-5 py-4">
          <button
            onClick={onCancel}
            disabled={pending}
            className="flex-1 rounded-md border border-border bg-surface px-4 py-2 text-sm hover:bg-neutral-800 disabled:opacity-50"
          >
            Annuler
          </button>
          <button
            onClick={onConfirm}
            disabled={!canConfirm}
            className={`flex-1 rounded-md px-4 py-2 text-sm font-semibold transition-colors ${
              canConfirm ? "bg-red-600 hover:bg-red-700" : "cursor-not-allowed bg-neutral-800 text-neutral-500"
            }`}
          >
            {pending ? "Activation en cours…" : "ACTIVER LE MODE RÉEL"}
          </button>
        </div>
      </div>
    </div>
  );
}
