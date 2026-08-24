"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

// Rendu éditable le 17/08/2026 (demande : "je veux pouvoir choisir le
// capital de paper trading moi-même") - le backend le permettait déjà
// depuis l'Étape 4 (`POST /paper-capital`), seul un contrôle côté
// interface manquait. Ne mute jamais la ligne existante : une nouvelle
// configuration est insérée (cohérent avec `paper_capital_config`,
// jamais un UPDATE) - l'historique des trades déjà simulés n'est jamais
// effacé, seul le point de départ du calcul change à partir de maintenant.
//
// Deux pools séparés depuis le 18/08/2026 (`marketType`) - un même
// composant réutilisé deux fois (spot et futures) dans VaultSummaryBar,
// jamais deux implémentations différentes pour la même interaction.
export default function PaperCapitalEditor({
  currentInitialCapital,
  marketType,
}: {
  currentInitialCapital: number;
  marketType: "spot" | "futures_perpetual";
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState(String(currentInitialCapital));
  const [requestedBy, setRequestedBy] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const parsed = Number(amount);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setError("Le montant doit être un nombre strictement positif.");
      return;
    }
    if (!requestedBy.trim()) {
      setError("Indique ton nom avant de confirmer.");
      return;
    }

    setError(null);
    setPending(true);
    try {
      const response = await fetch("/api/paper-capital", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initial_capital: parsed, set_by: requestedBy, market_type: marketType }),
      });
      if (!response.ok) {
        // Correctif du 18/08/2026 : la route proxy renvoie {error: "..."}
        // sur un refus de session (401), le backend renvoie {detail: "..."}
        // une fois la requête relayée - lire les deux, sinon le vrai motif
        // de l'échec restait invisible derrière un message générique.
        const body = await response.json().catch(() => ({}));
        setError(body.detail ?? body.error ?? `Échec de la mise à jour (code ${response.status}).`);
        return;
      }
      setEditing(false);
      router.refresh(); // recharge les données serveur (VaultSummaryBar) sans rechargement complet
    } catch {
      // Erreur réseau (fetch() lui-même a échoué, jamais de réponse HTTP
      // du tout) - distincte d'une réponse HTTP non-ok ci-dessus, jamais
      // silencieuse non plus.
      setError("Impossible de contacter le serveur - vérifie ta connexion et réessaie.");
    } finally {
      setPending(false);
    }
  }

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="text-xs text-neutral-500 underline decoration-dotted hover:text-neutral-300"
      >
        Modifier le capital initial ({marketType === "spot" ? "spot" : "futures"})
      </button>
    );
  }

  return (
    <div className="mt-2 space-y-2 rounded-md border border-border bg-neutral-900/60 p-3">
      <label className="block text-xs text-neutral-500">
        Nouveau capital initial {marketType === "spot" ? "spot" : "futures"} (USDT)
      </label>
      <input
        type="number"
        min="0"
        step="0.01"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        className="w-full rounded-md border border-border bg-neutral-900 px-3 py-1.5 text-sm"
      />
      <label className="block text-xs text-neutral-500">Ton nom (traçabilité)</label>
      <input
        value={requestedBy}
        onChange={(e) => setRequestedBy(e.target.value)}
        placeholder="Opérateur"
        className="w-full rounded-md border border-border bg-neutral-900 px-3 py-1.5 text-sm"
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      <p className="text-xs text-neutral-600">
        L&apos;historique des trades déjà simulés est conservé — seul le point de départ du calcul change.
        {marketType === "spot" ? " Le pool futures n'est jamais affecté." : " Le pool spot n'est jamais affecté."}
      </p>
      <div className="flex gap-2">
        <button
          onClick={() => setEditing(false)}
          disabled={pending}
          className="flex-1 rounded-md border border-border px-3 py-1.5 text-xs hover:bg-neutral-800 disabled:opacity-50"
        >
          Annuler
        </button>
        <button
          onClick={submit}
          disabled={pending}
          className="flex-1 rounded-md bg-sky-700 px-3 py-1.5 text-xs font-semibold hover:bg-sky-600 disabled:opacity-50"
        >
          {pending ? "…" : "Confirmer"}
        </button>
      </div>
    </div>
  );
}
