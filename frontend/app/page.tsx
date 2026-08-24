import Link from "next/link";
import {
  getCapitalAllocation,
  getDecisions,
  getExecutionModeStatus,
  getKillSwitch,
  getLiquidationCascadeRecent,
  getLogs,
  getPaperCapital,
  getPortfolioSummary,
  getPositions,
  getStrategiesLifecycle,
  getStrategiesPerformance,
} from "@/lib/api";
import KillSwitchButton from "@/components/KillSwitchButton";
import TradingViewChart from "@/components/TradingViewChart";
import PositionsTable from "@/components/PositionsTable";
import PortfolioSummaryCard from "@/components/PortfolioSummaryCard";
import TradeHistoryTable from "@/components/TradeHistoryTable";
import LiquidationCascadeCard from "@/components/LiquidationCascadeCard";
import DecisionsTable from "@/components/DecisionsTable";
import LogsList from "@/components/LogsList";
import StrategyPerformanceTable from "@/components/StrategyPerformanceTable";
import StrategyLifecycleTable from "@/components/StrategyLifecycleTable";
import ExecutionModePanel from "@/components/ExecutionModePanel";
import VaultSummaryBar from "@/components/VaultSummaryBar";

export const dynamic = "force-dynamic"; // toujours des données fraîches - pas de cache (supervision temps réel)

export default async function DashboardPage() {
  const [
    positions,
    closedPositions,
    portfolioSummary,
    liveBalances,
    paperCapitalSpot,
    paperCapitalFutures,
    capitalAllocation,
    strategiesLifecycle,
    decisions,
    liquidationCascadeOpinions,
    logs,
    strategies,
    killSwitch,
    executionModeStatus,
  ] = await Promise.all([
    getPositions(),
    getPositions("paper", "closed"),
    getPortfolioSummary(),
    getPortfolioSummary("real").then((s) => s.balances),
    getPaperCapital("spot"),
    getPaperCapital("futures_perpetual"),
    getCapitalAllocation(),
    getStrategiesLifecycle(),
    getDecisions(),
    getLiquidationCascadeRecent(),
    getLogs(),
    getStrategiesPerformance(),
    getKillSwitch(),
    getExecutionModeStatus(),
  ]);

  return (
    <main className="min-h-screen bg-background p-4 space-y-6 sm:p-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-lg font-semibold sm:text-xl">Plateforme Quant — Supervision</h1>
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <Link
            href="/strategies"
            className="rounded-md border border-border bg-surface px-3 py-2 text-sm hover:bg-neutral-800 sm:px-4"
          >
            Stratégies
          </Link>
          <Link
            href="/why-no-trade"
            className="rounded-md border border-border bg-surface px-3 py-2 text-sm hover:bg-neutral-800 sm:px-4"
          >
            Why No Trade ?
          </Link>
          <KillSwitchButton initialActive={killSwitch.active} />
        </div>
      </header>

      <VaultSummaryBar
        mode={executionModeStatus.current_mode}
        paperCapitalSpot={paperCapitalSpot}
        paperCapitalFutures={paperCapitalFutures}
        liveBalances={liveBalances}
        liveAllocations={capitalAllocation}
      />

      <TradingViewChart />

      <PortfolioSummaryCard summary={portfolioSummary} />

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-surface p-4">
          <h2 className="mb-3 text-sm font-semibold text-neutral-300">Positions ouvertes (paper)</h2>
          <div className="-mx-4 overflow-x-auto px-4">
            <PositionsTable positions={positions} />
          </div>
        </div>

        <div className="rounded-lg border border-border bg-surface p-4">
          <h2 className="mb-3 text-sm font-semibold text-neutral-300">Performance par stratégie</h2>
          <div className="-mx-4 overflow-x-auto px-4">
            <StrategyPerformanceTable strategies={strategies} />
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-semibold text-neutral-300">
          Cycle de vie des stratégies (Étape 3 — éviction/résurrection automatiques)
        </h2>
        <div className="-mx-4 overflow-x-auto px-4">
          <StrategyLifecycleTable strategies={strategiesLifecycle} />
        </div>
      </section>

      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-semibold text-neutral-300">
          Historique des trades — gains et pertes réalisés
        </h2>
        <div className="-mx-4 overflow-x-auto px-4">
          <TradeHistoryTable positions={closedPositions} />
        </div>
      </section>

      <LiquidationCascadeCard opinions={liquidationCascadeOpinions} />

      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-semibold text-neutral-300">Mode d&apos;exécution (ADR-0004/0008)</h2>
        <ExecutionModePanel initialStatus={executionModeStatus} />
      </section>

      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-semibold text-neutral-300">Décisions récentes</h2>
        <div className="-mx-4 overflow-x-auto px-4">
          <DecisionsTable decisions={decisions} />
        </div>
      </section>

      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-semibold text-neutral-300">Journal</h2>
        <LogsList logs={logs} />
      </section>
    </main>
  );
}
