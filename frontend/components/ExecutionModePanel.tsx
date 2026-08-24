"use client";

import { useState } from "react";
import type { ExecutionModeStatus, GovernanceCheckResult } from "@/lib/api";
import ActivateLiveModal from "@/components/ActivateLiveModal";

const MODE_LABELS: Record<string, string> = {
  backtest: "Backtest",
  paper: "Paper",
  real: "Live (réel)",
};

const CONFIRMATION_PHRASE = "ACTIVER LIVE";

const ATTESTATION_KEYS: { key: string; label: string }[] = [
  { key: "kill_switch_tested", label: "Kill switch testé" },
  { key: "backups_verified", label: "Sauvegardes vérifiées" },
  { key: "monitoring_active", label: "Monitoring actif" },
];

function PrerequisiteRow({ result }: { result: GovernanceCheckResult }) {
  return (
    <li className="flex items-start justify-between gap-4 py-1 text-sm">
      <span className="text-neutral-300">{result.check}</span>
      <span className={result.passed ? "text-green-400" : "text-red-400"}>
        {result.passed ? "OK" : (result.reason ?? "Non satisfait")}
      </span>
    </li>
  );
}

export default function ExecutionModePanel({ initialStatus }: { initialStatus: ExecutionModeStatus }) {
  const [status, setStatus] = useState(initialStatus);
  const [targetMode, setTargetMode] = useState(initialStatus.current_mode);
  const [requestedBy, setRequestedBy] = useState("");
  const [confirmationInput, setConfirmationInput] = useState("");
  const [showActivateLiveModal, setShowActivateLiveModal] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshStatus() {
    const response = await fetch("/api/execution-mode", { cache: "no-store" });
    if (response.ok) {
      setStatus(await response.json());
    }
  }

  async function submitModeChange(confirmationPhrase: string | null) {
    setError(null);
    setPending(true);
    try {
      const response = await fetch("/api/execution-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_mode: targetMode,
          requested_by: requestedBy,
          confirmation_phrase: confirmationPhrase,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        // Correctif du 18/08/2026 : la route proxy renvoie {error: "..."}
        // sur un refus de session (401), le backend renvoie {detail: "..."}
        // une fois relayé - lire les deux, sinon le vrai motif de l'échec
        // restait masqué derrière un message générique.
        setError(result.detail ?? result.error ?? `Changement de mode refusé (code ${response.status}).`);
        return;
      }
      await refreshStatus();
      setConfirmationInput("");
      setShowActivateLiveModal(false);
    } catch {
      // Erreur réseau (fetch() lui-même a échoué) - distincte d'une
      // réponse HTTP non-ok ci-dessus, jamais silencieuse non plus.
      setError("Impossible de contacter le serveur - vérifie ta connexion et réessaie.");
    } finally {
      setPending(false);
    }
  }

  function handleApplyClick() {
    setError(null);

    if (!requestedBy.trim()) {
      setError("Indique ton nom avant de confirmer un changement de mode.");
      return;
    }

    if (targetMode === "real") {
      // Mandat §10 : jamais un simple window.confirm() pour un passage
      // en argent réel - la modale dédiée affiche les prérequis et
      // exige la phrase exacte avant de permettre quoi que ce soit.
      setShowActivateLiveModal(true);
      return;
    }

    const confirmed = window.confirm(`Confirmer le passage en mode ${MODE_LABELS[targetMode] ?? targetMode} ?`);
    if (!confirmed) return;
    submitModeChange(null);
  }

  async function submitAttestation(key: string) {
    if (!requestedBy.trim()) {
      setError("Indique ton nom avant d'enregistrer une attestation.");
      return;
    }
    setError(null);
    setPending(true);
    try {
      const response = await fetch("/api/execution-mode/attestations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, attested_by: requestedBy }),
      });
      if (!response.ok) {
        // Correctif du 18/08/2026 : avant, une attestation échouée
        // n'affichait jamais rien - le bouton semblait fonctionner alors
        // que rien n'avait été enregistré.
        const result = await response.json().catch(() => ({}));
        setError(result.detail ?? result.error ?? `Échec de l'attestation (code ${response.status}).`);
        return;
      }
      await refreshStatus();
    } catch {
      setError("Impossible de contacter le serveur - vérifie ta connexion et réessaie.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4">
      {showActivateLiveModal && (
        <ActivateLiveModal
          confirmationPhrase={CONFIRMATION_PHRASE}
          prerequisites={status.live_prerequisites.results}
          requestedBy={requestedBy}
          confirmationInput={confirmationInput}
          onRequestedByChange={setRequestedBy}
          onConfirmationInputChange={setConfirmationInput}
          onConfirm={() => submitModeChange(confirmationInput)}
          onCancel={() => {
            setShowActivateLiveModal(false);
            setConfirmationInput("");
            setError(null);
          }}
          pending={pending}
          error={error}
        />
      )}

      <div className="flex items-center justify-between">
        <span className="text-sm text-neutral-400">Mode courant</span>
        <span className="rounded-md bg-neutral-800 px-3 py-1 text-sm font-semibold">
          {MODE_LABELS[status.current_mode] ?? status.current_mode}
        </span>
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Prérequis pour le mode Live
        </h3>
        {status.live_prerequisites.results.length === 0 ? (
          <p className="text-sm text-neutral-500">Aucun prérequis à afficher (déjà en mode Live).</p>
        ) : (
          <ul className="divide-y divide-border">
            {status.live_prerequisites.results.map((result) => (
              <PrerequisiteRow key={result.check} result={result} />
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-2 border-t border-border pt-3">
        <label className="block text-xs text-neutral-500">Ton nom (traçabilité, ADR-0008)</label>
        <input
          value={requestedBy}
          onChange={(e) => setRequestedBy(e.target.value)}
          placeholder="Opérateur"
          className="w-full rounded-md border border-border bg-neutral-900 px-3 py-1.5 text-sm"
        />

        <label className="block text-xs text-neutral-500">Nouveau mode</label>
        <select
          value={targetMode}
          onChange={(e) => setTargetMode(e.target.value)}
          className="w-full rounded-md border border-border bg-neutral-900 px-3 py-1.5 text-sm"
        >
          {Object.entries(MODE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>

        {error && !showActivateLiveModal && <p className="text-sm text-red-400">{error}</p>}

        <button
          onClick={handleApplyClick}
          disabled={pending}
          className={`w-full rounded-md px-4 py-2 text-sm font-semibold transition-colors ${
            targetMode === "real" ? "bg-red-600 hover:bg-red-700" : "bg-neutral-800 hover:bg-neutral-700"
          } ${pending ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          Appliquer le changement de mode
        </button>
      </div>

      <div className="space-y-2 border-t border-border pt-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Attestations manuelles (ADR-0008 - pas de détection automatique)
        </h3>
        <div className="flex flex-wrap gap-2">
          {ATTESTATION_KEYS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => submitAttestation(key)}
              disabled={pending}
              className="rounded-md border border-border bg-surface px-3 py-1.5 text-xs hover:bg-neutral-800 disabled:opacity-50"
            >
              Attester : {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
