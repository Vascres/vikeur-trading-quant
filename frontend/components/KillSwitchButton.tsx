"use client";

import { useState } from "react";

export default function KillSwitchButton({ initialActive }: { initialActive: boolean }) {
  const [active, setActive] = useState(initialActive);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    const next = !active;
    const confirmed = window.confirm(
      next
        ? "Confirmer l'activation du kill switch ? Toute nouvelle position sera bloquée (Phase 13)."
        : "Confirmer la désactivation du kill switch ?"
    );
    if (!confirmed) return;

    setError(null);
    setPending(true);
    try {
      const response = await fetch("/api/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: next }),
      });
      if (!response.ok) {
        // Correctif du 18/08/2026 : avant, un échec ici (ex. session
        // expirée) ne laissait AUCUNE trace visible - le bouton semblait
        // ne rien faire, sans jamais indiquer que le kill switch n'avait
        // PAS changé d'état. Critique sur ce contrôle précis : mieux vaut
        // un message d'erreur voyant qu'un silence trompeur.
        const body = await response.json().catch(() => ({}));
        setError(body.detail ?? body.error ?? `Échec de la mise à jour (code ${response.status}).`);
        return;
      }
      const result = await response.json();
      setActive(result.active);
    } catch {
      setError("Impossible de contacter le serveur - le kill switch n'a PAS changé d'état.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={toggle}
        disabled={pending}
        className={`rounded-md px-4 py-2 font-semibold transition-colors ${
          active ? "bg-red-600 hover:bg-red-700" : "bg-surface border border-border hover:bg-neutral-800"
        } ${pending ? "opacity-50 cursor-not-allowed" : ""}`}
      >
        {active ? "Kill switch : ACTIF - cliquer pour désactiver" : "Kill switch : inactif"}
      </button>
      {error && <p className="text-xs text-red-400 max-w-xs text-right">{error}</p>}
    </div>
  );
}
