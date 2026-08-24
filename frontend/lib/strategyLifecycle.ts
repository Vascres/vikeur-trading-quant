import type { StrategyLifecycleStatus } from "./api";

// Étape 3 (16/08/2026) : vocabulaire à 9 statuts (shared/strategy_lifecycle/states.py,
// backend) - libellés et styles centralisés ici plutôt que dupliqués
// dans chaque composant qui affiche un statut (StrategyLifecycleTable
// aujourd'hui, un futur "Why No Trade" demain).

const STATUS_LABELS: Record<StrategyLifecycleStatus, string> = {
  registered: "Enregistrée",
  collecting: "Collecte",
  experimental: "Expérimentale",
  validated: "Validée",
  production: "Production",
  under_review: "Sous surveillance",
  degraded: "Dégradée",
  suspended: "Suspendue",
  deprecated: "Obsolète",
};

// Trois familles visuelles : neutre (chemin de promotion, pas encore
// prouvé), positif (validé/production), alerte (chemin d'éviction) -
// jamais une couleur par statut sans rapport avec ce qu'elle signifie.
const STATUS_STYLES: Record<StrategyLifecycleStatus, string> = {
  registered: "bg-neutral-800 text-neutral-400",
  collecting: "bg-neutral-800 text-neutral-400",
  experimental: "bg-sky-900/60 text-sky-300",
  validated: "bg-green-900/60 text-green-300",
  production: "bg-green-900/60 text-green-300",
  under_review: "bg-amber-900/60 text-amber-300",
  degraded: "bg-orange-900/60 text-orange-300",
  suspended: "bg-red-900/60 text-red-300",
  deprecated: "bg-neutral-800 text-neutral-500",
};

export function lifecycleStatusLabel(status: StrategyLifecycleStatus | null): string {
  if (status === null) return "Non initialisée";
  return STATUS_LABELS[status];
}

export function lifecycleStatusStyle(status: StrategyLifecycleStatus | null): string {
  if (status === null) return "bg-neutral-800 text-neutral-500";
  return STATUS_STYLES[status];
}

// Mandat, chantier Étape 3 : "elle continue de tourner en Paper pour
// voir si elle se rétablit" (DEGRADED) vs "arrêt total de l'exécution"
// (SUSPENDED/DEPRECATED) - distinction utile à afficher explicitement,
// pas seulement déductible de la couleur du badge.
export function lifecycleStatusIsEvictionPath(status: StrategyLifecycleStatus | null): boolean {
  return status === "under_review" || status === "degraded" || status === "suspended" || status === "deprecated";
}
