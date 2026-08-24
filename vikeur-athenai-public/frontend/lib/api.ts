const API_URL = process.env.PUBLIC_API_URL ?? "http://localhost:8000";
const API_AUTH_TOKEN = process.env.API_AUTH_TOKEN ?? "";

// Ces fonctions ne s'exécutent JAMAIS dans le navigateur (uniquement dans
// des composants serveur Next.js) - le jeton n'est donc jamais exposé
// côté client (Module 1, §4.1, option B retenue).

export type Position = {
  id: number;
  exchange: string;
  symbol: string;
  execution_mode: string;
  entry_price: string;
  exit_price: string | null;
  quantity: string;
  realized_pnl: string | null;
  unrealized_pnl: string | null;
  status: string;
  opened_at: string;
  closed_at: string | null;
  // Ajoutés pour la traçabilité gains/pertes (aucun champ retiré ci-dessus -
  // le code existant qui consomme ce type continue de fonctionner à l'identique).
  decision_id: number | null;
  market_type: "spot" | "futures_perpetual";
  position_side: "long" | "short" | null;
};

export type PortfolioBalance = {
  exchange: string;
  total_value_reference_currency: string;
  reference_currency: string;
  taken_at: string;
  // Étape 4/5 (16/08/2026) : null = solde spot (convention historique,
  // cohérente avec l'API), "futures_perpetual" = solde de marge futures
  // (17/08/2026 - un exchange peut désormais apparaître deux fois ici).
  market_type: "futures_perpetual" | null;
};

export type PortfolioSummary = {
  balances: PortfolioBalance[];
  closed_trades: number;
  open_trades: number;
  total_realized_pnl: string;
  winning_trades: number;
  losing_trades: number;
};

export type Decision = {
  id: number;
  exchange: string;
  symbol: string;
  time: string;
  success_probability: number;
  expected_value: number;
  risk_reward_ratio: number;
  verdict: string;
  suggested_side: string;
  strategy_name: string;
  meta_decision_id: number | null; // ADR-0010 - présent si la décision provient d'une fusion multi-moteurs
  // ADR-0014 / ADR-0015 (Decision Explainability) - null pour toute
  // décision antérieure à ces chantiers (jamais reconstitué a posteriori).
  calibration_maturity: "collecting" | "preliminary" | "validated" | null;
  verdict_reason: string | null;
  execution_mode: "backtest" | "paper" | "real" | null;
  regime_type: string | null;
  fused_score: number | null;
};

// --- Decision Explainability (ADR-0014, ADR-0015) ---

export type EngineOpinion = {
  id: number;
  engine_name: string;
  suggested_side: string;
  score: number;
  confidence: number;
  uncertainty: number;
  rationale: Record<string, number>;
  time: string;
};

export type MetaDecision = {
  id: number;
  fusion_method: string;
  fused_score: number | null;
  suggested_side: string | null;
  weights_applied: Record<string, number>;
  calibration_run_id: number | null;
  success_probability: number | null;
  verdict: string;
  calibration_maturity: "collecting" | "preliminary" | "validated";
  verdict_reason: string | null;
  execution_mode: string;
  regime_type: string | null;
  regime_confidence: number | null;
};

export type RiskCheck = {
  rule_name: string;
  passed: boolean;
  reason: string | null;
  time: string;
};

export type CalibrationDetail = {
  method: string;
  sample_size: number;
  is_validated: boolean;
  brier_score: number | null;
  computed_at: string;
  reason: string | null;
};

export type CalibrationProgress = {
  trades_observed: number;
  minimum_for_preliminary: number;
  minimum_for_validated: number;
};

export type DecisionExplanation = {
  decision: Decision;
  meta_decision: MetaDecision | null;
  contributing_opinions: EngineOpinion[];
  risk_checks: RiskCheck[];
  calibration: CalibrationDetail | null;
  calibration_progress: CalibrationProgress;
};

export type LogEntry = {
  id: number;
  source_module: string;
  event_type: string;
  payload: Record<string, unknown>;
  time: string;
};

export type StrategyPerformance = {
  name: string;
  is_active: boolean;
  recommended_fraction: number | null;
  based_on_trade_count: number | null;
  computed_at: string | null;
};

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${API_AUTH_TOKEN}` },
  });
  if (!response.ok) {
    throw new Error(`Échec de l'appel API ${path} : ${response.status}`);
  }
  return response.json();
}

export const getPositions = (executionMode = "paper", status = "open") =>
  fetchJson<Position[]>(`/positions?execution_mode=${executionMode}&status=${status}`);

export const getPortfolioSummary = (executionMode = "paper") =>
  fetchJson<PortfolioSummary>(`/portfolio/summary?execution_mode=${executionMode}`);

export const getDecisions = (limit = 50) => fetchJson<Decision[]>(`/decisions?limit=${limit}`);

export const getDecisionExplanation = (decisionId: number) =>
  fetchJson<DecisionExplanation>(`/decisions/${decisionId}/explain`);

export const getLogs = (limit = 100) => fetchJson<LogEntry[]>(`/logs?limit=${limit}`);

export const getStrategiesPerformance = () => fetchJson<StrategyPerformance[]>(`/strategies/performance`);

export const getKillSwitch = () => fetchJson<{ active: boolean }>(`/kill-switch`);

// setKillSwitch n'existe plus ici : le bouton client appelle désormais
// directement la route proxy locale /api/kill-switch (même origine),
// qui seule connaît le jeton API (Module 1, §5).

export type GovernanceCheckResult = {
  check: string;
  passed: boolean;
  reason: string | null;
};

export type ExecutionModeHistoryEntry = {
  mode: string;
  previous_mode: string | null;
  changed_at: string;
  authorized_by: string;
};

export type ExecutionModeStatus = {
  current_mode: string;
  history: ExecutionModeHistoryEntry[];
  live_prerequisites: {
    overall_passed: boolean;
    results: GovernanceCheckResult[];
  };
};

export const getExecutionModeStatus = () => fetchJson<ExecutionModeStatus>(`/execution-mode`);

// setExecutionMode / recordGovernanceAttestation n'existent pas ici : le
// panneau client appelle directement les routes proxy locales
// /api/execution-mode et /api/execution-mode/attestations (même origine),
// qui seules connaissent le jeton API (même pattern que le kill switch,
// Module 1, §5).

export type PairDecision = {
  id: number;
  exchange: string;
  symbol: string;
  funding_rate_bps: number;
  gross_edge_bps: number;
  fees_bps: number;
  slippage_bps: number;
  net_edge_bps: number;
  execution_probability: number;
  execution_risk: "low" | "medium" | "high";
  pair_quality_score: number;
  decision: "accept" | "reject";
  status: string;
  created_at: string;
  resolved_at: string | null;
};

export type PairIncident = {
  id: number;
  pair_decision_id: number;
  incident_type: string;
  filled_leg: string;
  missing_leg: string;
  residual_exposure_notional: number;
  resolution_action: string;
  realized_cost_bps: number | null;
  detected_at: string;
  resolved_at: string | null;
};

export const getPairDecisions = (limit = 20) => fetchJson<PairDecision[]>(`/pair-decisions?limit=${limit}`);

export const getPairIncidents = (limit = 20) => fetchJson<PairIncident[]>(`/pair-incidents?limit=${limit}`);

// --- Liquidation Cascade (17/08/2026 - remplace la carte Pair Execution sur le dashboard) ---

export type LiquidationCascadeOpinion = {
  id: number;
  exchange: string;
  symbol: string;
  suggested_side: string;
  score: number;
  confidence: number;
  liquidation_notional_usd: number | null;
  momentum: number | null;
  spread_bps: number | null;
  time: string;
};

export const getLiquidationCascadeRecent = (limit = 20) =>
  fetchJson<LiquidationCascadeOpinion[]>(`/liquidation-cascade/recent?limit=${limit}`);

// --- Dual Vault (Étapes 4/5, 16/08/2026) ---

export type PaperCapital = {
  initial_capital: number;
  current_capital: number;
  reference_currency: string;
  set_at: string;
  set_by: string | null;
  // Deux pools séparés depuis le 18/08/2026 - "spot" par défaut si
  // absent (réponses d'un backend pas encore à jour), jamais une valeur
  // inventée pour "futures_perpetual" spécifiquement.
  market_type?: "spot" | "futures_perpetual";
};

export type CapitalAllocation = {
  exchange: string;
  allocation_pct: number;
  set_at: string;
  set_by: string | null;
};

export const getPaperCapital = (marketType: "spot" | "futures_perpetual" = "spot") =>
  fetchJson<PaperCapital>(`/paper-capital?market_type=${marketType}`);

export const getCapitalAllocation = () => fetchJson<CapitalAllocation[]>(`/capital-allocation`);

// setPaperCapital / setCapitalAllocation n'existent pas ici : les
// formulaires côté client appellent les routes proxy locales
// /api/paper-capital et /api/capital-allocation (même origine), qui
// seules connaissent le jeton API (même pattern que le kill switch et
// le mode d'exécution, Module 1, §5).

// --- Strategy Lifecycle (Étape 3, 16/08/2026) ---

export type StrategyLifecycleStatus =
  | "registered"
  | "collecting"
  | "experimental"
  | "validated"
  | "production"
  | "under_review"
  | "degraded"
  | "suspended"
  | "deprecated";

export type StrategyLifecycle = {
  strategy_id: number;
  name: string;
  status: StrategyLifecycleStatus | null;
  reason: string | null;
  ev_net_bps: number | null;
  cumulative_pnl_reference_currency: string | null;
  profit_factor: number | null;
  sample_size: number | null;
  transitioned_at: string | null;
};

export const getStrategiesLifecycle = () => fetchJson<StrategyLifecycle[]>(`/strategies/lifecycle`);

export type StrategyPerformanceMetrics = {
  strategy_id: number;
  execution_mode: string;
  trade_count: number;
  days_observed: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  calmar_ratio: number | null;
  max_drawdown_pct: number | null;
};

export const getStrategyPerformanceMetrics = (strategyId: number, executionMode = "paper") =>
  fetchJson<StrategyPerformanceMetrics>(
    `/strategies/${strategyId}/performance-metrics?execution_mode=${executionMode}`
  );

// --- Why No Trade (mandat §21, 16/08/2026) ---

export type WhyNoTradeStage = {
  stage: string;
  label: string;
  count: number;
};

export type WhyNoTradeCostModelNote = {
  cleared: number;
  total: number;
  note: string;
};

export type WhyNoTradeFunnel = {
  since: string;
  execution_mode: string;
  funnel: WhyNoTradeStage[];
  cost_model_note: WhyNoTradeCostModelNote;
};

export const getWhyNoTrade = (executionMode = "paper", sinceHours = 24) =>
  fetchJson<WhyNoTradeFunnel>(`/why-no-trade?execution_mode=${executionMode}&since_hours=${sinceHours}`);
