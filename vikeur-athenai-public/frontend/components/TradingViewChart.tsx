"use client";

import { useEffect, useRef } from "react";

export default function TradingViewChart({ symbol = "HTX:BTCUSDT" }: { symbol?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol,
      interval: "1",
      timezone: "Etc/UTC",
      theme: "dark",
      style: "1",
      locale: "fr",
      backgroundColor: "rgba(11, 14, 20, 1)",
      hide_top_toolbar: false,
      allow_symbol_change: false,
    });
    containerRef.current.appendChild(script);
  }, [symbol]);

  return (
    <div className="rounded-lg border border-border bg-surface p-2 h-[500px]">
      <div ref={containerRef} className="tradingview-widget-container h-full w-full" />
    </div>
  );
}
