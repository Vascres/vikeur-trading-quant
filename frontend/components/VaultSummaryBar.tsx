import type { CapitalAllocation, PaperCapital, PortfolioBalance } from "@/lib/api";
import PaperCapitalEditor from "@/components/PaperCapitalEditor";

function formatCurrency(value: number, currency = "USDT"): string {
  return `${value.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

// Étapes 4/5 (16/08/2026) : le "Mur de Fer" du mandat - deux blocs
// visuellement distincts, jamais fusionnés, pour que Paper et Live ne
// puissent jamais être confondus d'un coup d'œil (mandat §9 : "un
// système extrêmement clair"). Étendu le 17/08/2026 : solde de marge
// futures affiché séparément du solde spot côté Live. Étendu à nouveau
// le 18/08/2026 : le Paper Vault distingue désormais lui aussi ses deux
// pools (spot/futures), chacun avec son propre suivi de P&L et son
// propre éditeur - décision confirmée avec l'opérateur : un seul pool
// PAR market_type, partagé entre tous les exchanges (jamais un pool
// par exchange), cohérent avec le choix "100% Binance" en cours.
export default function VaultSummaryBar({
  mode,
  paperCapitalSpot,
  paperCapitalFutures,
  liveBalances,
  liveAllocations,
}: {
  mode: string;
  paperCapitalSpot: PaperCapital;
  paperCapitalFutures: PaperCapital;
  liveBalances: PortfolioBalance[];
  liveAllocations: CapitalAllocation[];
}) {
  const modeIsLive = mode === "real";
  const spotBalances = liveBalances.filter((b) => b.market_type === null);
  const futuresBalances = liveBalances.filter((b) => b.market_type === "futures_perpetual");

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div
        className={`rounded-lg border p-4 ${
          modeIsLive ? "border-border bg-surface" : "border-sky-700 bg-sky-950/40"
        }`}
      >
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-sky-400">Paper Vault</span>
          {!modeIsLive && (
            <span className="rounded bg-sky-900 px-2 py-0.5 text-xs font-semibold text-sky-300">
              Mode actif
            </span>
          )}
        </div>

        <div className="mb-2">
          <div className="text-xl font-semibold sm:text-2xl">
            {formatCurrency(paperCapitalSpot.current_capital, paperCapitalSpot.reference_currency)}
          </div>
          <div className="mt-1 text-xs text-neutral-500">
            Capital virtuel (spot) — initial{" "}
            {formatCurrency(paperCapitalSpot.initial_capital, paperCapitalSpot.reference_currency)}
          </div>
          <div className="mt-2">
            <PaperCapitalEditor currentInitialCapital={paperCapitalSpot.initial_capital} marketType="spot" />
          </div>
        </div>

        <div className="border-t border-border/60 pt-2">
          <div className="text-lg font-semibold sm:text-xl">
            {formatCurrency(paperCapitalFutures.current_capital, paperCapitalFutures.reference_currency)}
          </div>
          <div className="mt-1 text-xs text-neutral-500">
            Capital virtuel (futures) — initial{" "}
            {formatCurrency(paperCapitalFutures.initial_capital, paperCapitalFutures.reference_currency)}
          </div>
          <div className="mt-2">
            <PaperCapitalEditor
              currentInitialCapital={paperCapitalFutures.initial_capital}
              marketType="futures_perpetual"
            />
          </div>
        </div>
      </div>

      <div
        className={`rounded-lg border p-4 ${
          modeIsLive ? "border-red-700 bg-red-950/30" : "border-border bg-surface"
        }`}
      >
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-red-400">Live Vault</span>
          {modeIsLive && (
            <span className="rounded bg-red-900 px-2 py-0.5 text-xs font-semibold text-red-300">
              Mode actif — capital réel engagé
            </span>
          )}
        </div>

        {spotBalances.length === 0 ? (
          <p className="text-sm text-neutral-500">Aucun instantané de portefeuille réel disponible.</p>
        ) : (
          spotBalances.map((balance) => {
            const allocation = liveAllocations.find((a) => a.exchange === balance.exchange);
            const total = Number(balance.total_value_reference_currency);
            const allocatedAmount = allocation ? (total * allocation.allocation_pct) / 100 : null;

            return (
              <div key={`${balance.exchange}-spot`} className="mb-2 last:mb-0">
                <div className="text-xl font-semibold sm:text-2xl">
                  {formatCurrency(total, balance.reference_currency)}
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  {balance.exchange} (spot) —{" "}
                  {allocation
                    ? `${allocation.allocation_pct}% alloué (${formatCurrency(
                        allocatedAmount as number,
                        balance.reference_currency
                      )} exposés à Vikeur)`
                    : "Aucune allocation configurée — mode réel interdit (Étape 6, mur d'allocation)"}
                </div>
              </div>
            );
          })
        )}

        {futuresBalances.length > 0 && (
          <div className="mt-3 border-t border-border/60 pt-3">
            {futuresBalances.map((balance) => (
              <div key={`${balance.exchange}-futures`} className="mb-2 last:mb-0">
                <div className="text-lg font-semibold sm:text-xl">
                  {formatCurrency(Number(balance.total_value_reference_currency), balance.reference_currency)}
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  {balance.exchange} (futures) — solde de marge, hors mur d&apos;allocation (Étapes 7-8)
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
