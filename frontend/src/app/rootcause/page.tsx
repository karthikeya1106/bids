"use client";
import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Title, Tooltip, Legend, Filler, type ChartOptions,
} from "chart.js";
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Crosshair,
  Layers, RefreshCw, TrendingDown, TrendingUp,
} from "lucide-react";
import { getRootCause } from "@/lib/api";
import AdaptiveModule, { type AdaptiveModulePayload } from "@/components/AdaptiveModule";
import { formatCompact, formatCurrency, formatNumber, formatPercent } from "@/lib/format";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

interface Anomaly {
  month: string;
  value: number;
  expected: number;
  gap: number;
  gap_pct: number | null;
  z_score: number;
  seasonal_index: number;
  type: "drop" | "spike";
  severity: "low" | "medium" | "high";
}

interface DimensionRow {
  label: string;
  current: number;
  baseline: number;
  contribution: number;
  change_pct: number | null;
}

interface SelectedAnomaly {
  month: string;
  type: string;
  severity: string;
  z_score: number;
  expected: number;
  narrative: string;
  revenue: { current: number; baseline: number; gap: number };
  effects: Record<"volume" | "price" | "mix", { value: number; share: number }>;
  drivers: {
    volume: { orders: number; baseline_orders: number };
    price: { aov: number; baseline_aov: number; change_pct: number | null };
    discount: { current: number; baseline: number; change_pp: number; profit_effect: number };
    margin: { current: number; baseline: number; change_pp: number; profit: number };
    customers: {
      new: number; new_revenue: number; new_revenue_baseline: number;
      new_revenue_share: number; returning_revenue: number;
      returning_revenue_baseline: number; top10_share: number; top10_revenue: number;
    };
    delivery: { current_lag: number; baseline_lag: number; change_days: number };
    seasonality: { calendar_month: number; factor: number; index: number | null };
    orders: { current: number; baseline: number };
  };
  dimensions: Record<"category" | "sub_category" | "region" | "segment" | "product", DimensionRow[]>;
}

interface FishboneFactor {
  factor: string;
  confidence: number;
  impact: number;
  evidence: string;
}

interface RootCauseData {
  has_data: boolean;
  monthly_series: {
    month: string; sales: number; profit: number; orders: number;
    margin: number; expected: number; seasonal_index: number;
  }[];
  anomalies: Anomaly[];
  selected: SelectedAnomaly | null;
  fishbone: Record<string, FishboneFactor[]>;
  top_root_cause: {
    branch: string; factor: string; confidence: number; impact: number; evidence: string;
  } | null;
  summary: {
    months_monitored: number; anomaly_count: number; drops: number; spikes: number;
    worst: Anomaly | null; largest_swing: number; net_swing: number;
    period_from: string | null; period_to: string | null;
  } | null;
}

const SEVERITY_LABEL: Record<string, string> = { low: "Low", medium: "Medium", high: "High" };
const BRANCH_ICONS: Record<string, typeof Layers> = {
  Product: Layers,
  Process: Activity,
  People: Crosshair,
  External: TrendingUp,
};

function SparkMetric({
  label, value, sub, icon: Icon, index,
}: {
  label: string; value: string; sub: string; icon: typeof Activity; index: number;
}) {
  return (
    <div className="kpi-card animate-fade-up" style={{ animationDelay: `${index * 60}ms`, opacity: 0 }}>
      <div className="kpi-accent-bar" />
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 10 }}>
        <span className="kpi-label" style={{ marginBottom: 0 }}>{label}</span>
        <div className="kpi-icon-box" style={{ width: 30, height: 30 }}>
          <Icon size={14} color="#000000" />
        </div>
      </div>
      <div className="kpi-value" style={{ fontSize: 25, marginBottom: 6 }}>{value}</div>
      <div className="kpi-sub">{sub}</div>
    </div>
  );
}

function ContributionList({
  title, rows, emptyLabel,
}: {
  title: string; rows: DimensionRow[]; emptyLabel: string;
}) {
  const max = Math.max(...rows.map((row) => Math.abs(row.contribution)), 1);
  return (
    <div>
      <div style={{
        fontSize: 10.5, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.07em", color: "var(--text-muted)", marginBottom: 9,
      }}>
        {title}
      </div>
      {rows.length === 0 && (
        <p style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{emptyLabel}</p>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        {rows.map((row) => (
          <div key={row.label}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 3 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{row.label}</span>
              <span style={{
                fontSize: 11.5, fontWeight: 700, fontVariantNumeric: "tabular-nums",
                color: row.contribution < 0 ? "#b91c1c" : "#047857",
              }}>
                {row.contribution < 0 ? "−" : "+"}{formatCompact(Math.abs(row.contribution))}
              </span>
            </div>
            <div className="progress-track" style={{ height: 4 }}>
              <div
                className="progress-fill"
                style={{
                  width: `${(Math.abs(row.contribution) / max) * 100}%`,
                  background: row.contribution < 0 ? "#111111" : "#9ca3af",
                }}
              />
            </div>
            <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
              {formatCompact(row.current)} vs {formatCompact(row.baseline)} run-rate
              {row.change_pct !== null ? ` · ${row.change_pct > 0 ? "+" : ""}${row.change_pct.toFixed(1)}%` : ""}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function RootCausePage() {
  const [data, setData] = useState<RootCauseData | null>(null);
  const [month, setMonth] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const reload = () => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  };

  const selectMonth = (next: string | null) => {
    setLoading(true);
    if (next === month) setReloadKey((key) => key + 1);
    else setMonth(next);
  };

  useEffect(() => {
    let cancelled = false;
    getRootCause(month ?? undefined)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError("");
      })
      .catch(() => {
        if (!cancelled) setError("Could not load root cause analysis. Make sure the FastAPI server is running on port 8000.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [month, reloadKey]);

  const refresh = () => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  };

  const adaptive = data && (data as { mode?: string }).mode === "adaptive"
    ? (data as unknown as AdaptiveModulePayload)
    : null;

  const header = (
    <div className="page-header" style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="page-title">
            <div className="page-title-icon"><AlertTriangle size={18} /></div>
            Root Cause Analysis
          </div>
          <p className="page-subtitle">
            {adaptive
              ? "Statistically tested drivers behind the observed outcome, with effect sizes and correction for multiple comparisons."
              : "Seasonally adjusted anomaly detection, revenue-gap decomposition and an Ishikawa causal tree."}
          </p>
        </div>
        <button className="btn-ghost" onClick={() => selectMonth(null)} style={{ fontSize: 12 }}>
          <RefreshCw size={13} /> Reset to worst month
        </button>
      </div>
    </div>
  );

  if (loading && !data) {
    return (
      <div>
        {header}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 14, marginBottom: 14 }}>
          {[...Array(4)].map((_, i) => <div key={i} className="skeleton" style={{ height: 124 }} />)}
        </div>
        <div className="skeleton" style={{ height: 300, marginBottom: 14 }} />
        <div className="skeleton" style={{ height: 240 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "64px 24px" }}>
          <AlertTriangle size={30} color="#b91c1c" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>Root cause analysis unavailable</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 440, margin: "0 auto 18px" }}>{error}</p>
          <button className="btn-primary" onClick={reload}><RefreshCw size={14} /> Try again</button>
        </div>
      </div>
    );
  }

  if (adaptive) {
    return (
      <div>
        {header}
        <AdaptiveModule payload={adaptive} onRefresh={refresh} />
      </div>
    );
  }

  if (!data?.has_data || !data.summary) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "72px 24px" }}>
          <AlertTriangle size={28} color="#111111" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 6 }}>No history to analyse</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 430, margin: "0 auto" }}>
            Anomaly detection needs at least several months of order history. Upload a dataset to begin.
          </p>
        </div>
      </div>
    );
  }

  const { summary, anomalies, monthly_series, selected, fishbone, top_root_cause } = data;
  const anomalyByMonth = new Map(anomalies.map((item) => [item.month, item]));
  const selectedMonth = selected?.month ?? null;
  const worst = summary.worst;

  const chartData = {
    labels: monthly_series.map((point) => point.month),
    datasets: [
      {
        label: "Expected run-rate",
        data: monthly_series.map((point) => point.expected),
        borderColor: "#9ca3af",
        borderDash: [5, 4],
        borderWidth: 1.6,
        pointRadius: 0,
        fill: false,
        tension: 0.3,
      },
      {
        label: "Revenue",
        data: monthly_series.map((point) => point.sales),
        borderColor: "#000000",
        backgroundColor: "rgba(0,0,0,0.05)",
        borderWidth: 2.4,
        fill: true,
        tension: 0.3,
        pointRadius: (context: { dataIndex: number }) => {
          const anomaly = anomalyByMonth.get(monthly_series[context.dataIndex]?.month ?? "");
          if (!anomaly) return 2.5;
          return anomaly.severity === "high" ? 6 : 5;
        },
        pointBackgroundColor: (context: { dataIndex: number }) => {
          const anomaly = anomalyByMonth.get(monthly_series[context.dataIndex]?.month ?? "");
          if (!anomaly) return "#000000";
          return anomaly.type === "drop" ? "#dc2626" : "#d97706";
        },
        pointBorderColor: "#ffffff",
        pointBorderWidth: 1.5,
        pointHoverRadius: 7,
      },
    ],
  };

  const chartOptions: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        labels: { color: "#111111", boxWidth: 12, padding: 16, font: { size: 11, weight: 600 } },
      },
      tooltip: {
        backgroundColor: "#000000",
        padding: 10,
        callbacks: {
          label: (context) => ` ${context.dataset.label}: ${formatCurrency(context.parsed.y)}`,
          afterBody: (items) => {
            const anomaly = anomalyByMonth.get(monthly_series[items[0]?.dataIndex ?? -1]?.month ?? "");
            if (!anomaly) return [];
            return [
              `${anomaly.type === "drop" ? "Shortfall" : "Excess"}: ${formatCurrency(anomaly.gap)}`,
              `Robust z-score: ${anomaly.z_score}`,
              `Severity: ${SEVERITY_LABEL[anomaly.severity]}`,
            ];
          },
        },
      },
    },
    scales: {
      x: {
        ticks: { color: "#6b7280", maxTicksLimit: 14, font: { size: 10 } },
        grid: { color: "#f3f4f6" },
      },
      y: {
        ticks: { color: "#6b7280", callback: (value) => formatCompact(Number(value)), font: { size: 10 } },
        grid: { color: "#f3f4f6" },
      },
    },
  };

  return (
    <div>
      {header}

      {/* Summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(205px, 1fr))", gap: 14, marginBottom: 14 }}>
        <SparkMetric
          label="Anomalies flagged"
          value={formatNumber(summary.anomaly_count)}
          sub={`${summary.drops} drops · ${summary.spikes} spikes over ${summary.months_monitored} months`}
          icon={AlertTriangle}
          index={0}
        />
        <SparkMetric
          label="Worst drop"
          value={worst ? formatCompact(Math.abs(worst.gap)) : "—"}
          sub={worst ? `${worst.month} — ${formatPercent(worst.gap_pct ?? 0)} vs run-rate` : "No drops recorded"}
          icon={TrendingDown}
          index={1}
        />
        <SparkMetric
          label="Net anomaly swing"
          value={formatCompact(summary.net_swing)}
          sub="Sum of every flagged month's gap"
          icon={Activity}
          index={2}
        />
        <SparkMetric
          label="Period monitored"
          value={`${summary.months_monitored}`}
          sub={summary.period_from && summary.period_to ? `${summary.period_from} → ${summary.period_to}` : ""}
          icon={Layers}
          index={3}
        />
      </div>

      {/* Timeline */}
      <div className="chart-panel animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div className="chart-title">Revenue vs seasonally adjusted expectation</div>
            <div className="chart-subtitle" style={{ marginBottom: 0 }}>
              <span style={{ color: "#dc2626", fontWeight: 700 }}>● Drop</span>
              <span style={{ marginLeft: 12, color: "#d97706", fontWeight: 700 }}>● Spike</span>
              <span style={{ marginLeft: 14 }}>robust z ≥ 2.0 · trend and month-of-year removed</span>
            </div>
          </div>
        </div>
        <div style={{ height: 280, marginTop: 14 }}>
          <Line data={chartData} options={chartOptions} />
        </div>
      </div>

      {/* Anomaly picker */}
      <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 6, marginBottom: 14 }}>
        {anomalies.map((anomaly) => {
          const isActive = selectedMonth === anomaly.month;
          const isDrop = anomaly.type === "drop";
          return (
            <button
              key={anomaly.month}
              onClick={() => selectMonth(anomaly.month)}
              className={isActive ? "btn-primary" : "btn-ghost"}
              style={{ flexShrink: 0, display: "flex", alignItems: "center", gap: 7, padding: "7px 12px" }}
              aria-pressed={isActive}
            >
              {isDrop ? <ArrowDownRight size={13} /> : <ArrowUpRight size={13} />}
              <span style={{ fontWeight: 700 }}>{anomaly.month}</span>
              <span style={{ fontSize: 11, opacity: 0.75 }}>
                {anomaly.gap_pct !== null ? `${anomaly.gap_pct > 0 ? "+" : ""}${anomaly.gap_pct.toFixed(0)}%` : ""}
              </span>
            </button>
          );
        })}
      </div>

      {selected && (
        <>
          {/* Root cause banner */}
          {top_root_cause && (
            <div
              className="panel animate-fade-up"
              style={{
                padding: "16px 20px", marginBottom: 14, opacity: 0,
                borderLeft: "4px solid #000000",
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
                <div style={{
                  width: 38, height: 38, borderRadius: 10, background: "#000000",
                  display: "grid", placeItems: "center", flexShrink: 0,
                }}>
                  <Crosshair size={18} color="#ffffff" />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
                    <span style={{
                      fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
                      textTransform: "uppercase", color: "var(--text-muted)",
                    }}>
                      Primary driver · {top_root_cause.branch}
                    </span>
                    <span className="tag tag-info">{formatPercent(top_root_cause.confidence * 100, 0)} confidence</span>
                    <span className="tag" style={{ background: "#f3f4f6", borderColor: "var(--border)", color: "#111111" }}>
                      {top_root_cause.impact < 0 ? "−" : "+"}{formatCompact(Math.abs(top_root_cause.impact))} impact
                    </span>
                  </div>
                  <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 5 }}>{top_root_cause.factor}</div>
                  <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.6 }}>
                    {top_root_cause.evidence}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Month summary + effects */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 14 }}>
            <div className="panel panel-body animate-fade-up" style={{ flex: "1 1 420px", minWidth: 0, opacity: 0 }}>
              <div className="panel-header" style={{ marginBottom: 10 }}>
                <span className="panel-title">{selected.month} — what happened</span>
                <div style={{ display: "flex", gap: 6 }}>
                  <span className={`tag ${selected.type === "drop" ? "tag-danger" : "tag-warning"}`}>
                    {selected.type === "drop" ? "Shortfall" : "Upside"}
                  </span>
                  <span className="tag" style={{ background: "#f3f4f6", borderColor: "var(--border)", color: "#111111" }}>
                    z {selected.z_score}
                  </span>
                </div>
              </div>
              <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.65, marginBottom: 14 }}>
                {selected.narrative}
              </p>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 14 }}>
                {([
                  ["Actual", selected.revenue.current],
                  ["Expected", selected.expected ?? selected.revenue.baseline],
                  ["Gap", selected.revenue.gap],
                ] as const).map(([label, value]) => (
                  <div key={label} style={{
                    background: "#f9fafb", border: "1px solid var(--border)",
                    borderRadius: 9, padding: "10px 12px",
                  }}>
                    <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 3 }}>
                      {label}
                    </div>
                    <div style={{
                      fontSize: 15, fontWeight: 800, fontVariantNumeric: "tabular-nums",
                      color: label === "Gap" ? (value < 0 ? "#b91c1c" : "#047857") : "#111111",
                    }}>
                      {formatCurrency(value)}
                    </div>
                  </div>
                ))}
              </div>

              <div style={{
                fontSize: 10.5, fontWeight: 700, textTransform: "uppercase",
                letterSpacing: "0.07em", color: "var(--text-muted)", marginBottom: 8,
              }}>
                Gap decomposition
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {(["volume", "price", "mix"] as const).map((key) => {
                  const effect = selected.effects[key];
                  const label = key === "volume" ? "Order volume" : key === "price" ? "Price / basket mix" : "Interaction";
                  return (
                    <div key={key}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, marginBottom: 3 }}>
                        <span style={{ fontWeight: 600 }}>{label}</span>
                        <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 700 }}>
                          {effect.value < 0 ? "−" : "+"}{formatCompact(Math.abs(effect.value))}
                          <span style={{ color: "var(--text-muted)", fontWeight: 500 }}> ({effect.share.toFixed(0)}% of gap)</span>
                        </span>
                      </div>
                      <div className="progress-track" style={{ height: 4 }}>
                        <div
                          className="progress-fill"
                          style={{
                            width: `${Math.min(Math.abs(effect.share), 100)}%`,
                            background: effect.value < 0 ? "#111111" : "#9ca3af",
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="panel panel-body animate-fade-up" style={{ flex: "0 1 340px", minWidth: 270, opacity: 0 }}>
              <div className="panel-header" style={{ marginBottom: 12 }}>
                <span className="panel-title">Operational drivers</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9, marginBottom: 12 }}>
                {[
                  ["Orders", formatNumber(selected.drivers.orders.current), `${selected.drivers.orders.baseline.toFixed(0)} expected`],
                  ["Avg order value", formatCurrency(selected.drivers.price.aov), `${(selected.drivers.price.change_pct ?? 0).toFixed(1)}% vs run-rate`],
                  ["Avg discount", formatPercent(selected.drivers.discount.current), `${selected.drivers.discount.change_pp > 0 ? "+" : ""}${selected.drivers.discount.change_pp.toFixed(1)}pp`],
                  ["Margin", formatPercent(selected.drivers.margin.current), `${selected.drivers.margin.change_pp > 0 ? "+" : ""}${selected.drivers.margin.change_pp.toFixed(1)}pp`],
                  ["Ship lag", `${selected.drivers.delivery.current_lag.toFixed(1)}d`, `${selected.drivers.delivery.change_days > 0 ? "+" : ""}${selected.drivers.delivery.change_days.toFixed(1)}d`],
                  ["Top 10 share", formatPercent(selected.drivers.customers.top10_share), formatCompact(selected.drivers.customers.top10_revenue)],
                ].map(([label, value, sub]) => (
                  <div key={label} style={{
                    background: "#f9fafb", border: "1px solid var(--border)",
                    borderRadius: 8, padding: "8px 10px",
                  }}>
                    <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)", marginBottom: 2 }}>
                      {label}
                    </div>
                    <div style={{ fontSize: 13.5, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>{value}</div>
                    <div style={{ fontSize: 9.5, color: "var(--text-muted)" }}>{sub}</div>
                  </div>
                ))}
              </div>

              <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, marginBottom: 6 }}>
                  <span style={{ color: "var(--text-muted)" }}>New-customer revenue</span>
                  <span style={{ fontWeight: 700 }}>{formatCompact(selected.drivers.customers.new_revenue)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, marginBottom: 6 }}>
                  <span style={{ color: "var(--text-muted)" }}>Returning-customer revenue</span>
                  <span style={{ fontWeight: 700 }}>{formatCompact(selected.drivers.customers.returning_revenue)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5 }}>
                  <span style={{ color: "var(--text-muted)" }}>Discount profit effect</span>
                  <span style={{
                    fontWeight: 700,
                    color: selected.drivers.discount.profit_effect < 0 ? "#b91c1c" : "#047857",
                  }}>
                    {formatCurrency(selected.drivers.discount.profit_effect)}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Dimension drivers */}
          <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
            <div className="panel-header">
              <span className="panel-title">Where the gap came from</span>
              <span className="tag tag-info">{selected.month}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 20 }}>
              <ContributionList title="Sub-category" rows={selected.dimensions.sub_category} emptyLabel="No sub-category moved materially." />
              <ContributionList title="Region" rows={selected.dimensions.region} emptyLabel="Regions moved together." />
              <ContributionList title="Account segment" rows={selected.dimensions.segment} emptyLabel="No segment-specific movement." />
              <ContributionList title="Products" rows={selected.dimensions.product} emptyLabel="No single product stands out." />
            </div>
          </div>

          {/* Fishbone */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 14, fontWeight: 800, marginBottom: 4 }}>Ishikawa fishbone — causal tree</div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 14 }}>
              Confidence is the share of the measured gap each factor explains; dollar impact is quantified where possible.
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
            {Object.entries(fishbone).map(([branch, factors], branchIndex) => {
              const Icon = BRANCH_ICONS[branch] ?? Layers;
              return (
                <div
                  key={branch}
                  className="panel panel-body animate-fade-up"
                  style={{ opacity: 0, animationDelay: `${branchIndex * 60}ms` }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 13 }}>
                    <div style={{
                      width: 30, height: 30, borderRadius: 8, background: "#000000",
                      display: "grid", placeItems: "center",
                    }}>
                      <Icon size={15} color="#ffffff" />
                    </div>
                    <span style={{ fontWeight: 800, fontSize: 13 }}>{branch}</span>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {factors.map((factor) => (
                      <div key={factor.factor}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
                          <span style={{ fontSize: 12, fontWeight: 700 }}>{factor.factor}</span>
                          <span style={{ fontSize: 11, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
                            {formatPercent(factor.confidence * 100, 0)}
                          </span>
                        </div>
                        <div className="progress-track" style={{ height: 4, marginBottom: 5 }}>
                          <div
                            className="progress-fill"
                            style={{ width: `${factor.confidence * 100}%`, background: "#111111" }}
                          />
                        </div>
                        <p style={{ fontSize: 10.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                          {factor.evidence}
                        </p>
                        {factor.impact !== 0 && (
                          <div style={{
                            fontSize: 10, fontWeight: 700, marginTop: 4,
                            color: factor.impact < 0 ? "#b91c1c" : "#047857",
                          }}>
                            {factor.impact < 0 ? "−" : "+"}{formatCompact(Math.abs(factor.impact))} measured impact
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
