// Mandat §14 (Strategy Dashboard, 16/08/2026) - formatage des ratios de
// performance. Fonctions pures, séparées du composant pour rester
// testables sans rendu React (même précédent que lib/strategyLifecycle.ts).

const MIN_DAYS_FOR_RELIABLE_RATIO = 30;

export function formatRatio(value: number | null): string {
  if (value === null) return "—";
  return value.toFixed(2);
}

export function formatDrawdownPct(value: number | null): string {
  if (value === null) return "—";
  return `${value.toFixed(1)}%`;
}

// Mandat, principe général déjà appliqué ailleurs (PortfolioSummaryCard,
// seuil de 30 trades) : un Sharpe/Sortino/Calmar calculé sur peu de
// jours observés n'est pas fiable statistiquement - jamais présenté
// avec la même autorité visuelle qu'un ratio établi sur un échantillon
// suffisant.
export function isRatioSampleReliable(daysObserved: number): boolean {
  return daysObserved >= MIN_DAYS_FOR_RELIABLE_RATIO;
}
