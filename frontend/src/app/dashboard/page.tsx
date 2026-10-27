"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Title, Tooltip, Legend, Filler, type ChartOptions,
} from "chart.js";
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, BarChart3,
  CheckCircle2, DollarSign, Info, LayoutDashboard, RefreshCw, ShoppingCart,
  TrendingUp, Upload, Users,
} from "lucide-react";
import { getDashboard } from "@/lib/api";
import AdaptiveModule, { type AdaptiveModulePayload } from "@/components/AdaptiveModule";
import {
  deltaTone, formatCompact, formatCurrency, formatDelta,
  formatNumber, formatPercent,
} from "@/lib/format";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

interface Kpi {
  key: string;
  label: string;
  value: number;
  previous: number;
  delta_pct: number | null;
  unit: string;
  format: "currency" | "number" | "percent";
  spark: { month: string; value: number }[];
}

interface DashboardData {
  has_data: boolean;
  meta: {
    dataset_name: string; org_name: string | null; source: string;
    rows: number; customers: number; orders: number;
    date_from: string; date_to: string;
  } | null;
  period: {
    days: number; current_from: string; current_to: string;
    previous_from: string; previous_to: string;
  } | null;
  kpis: Kpi[];
  revenue_trend: { month: string; sales: number; profit: number; orders: number; margin: number; aov: number }[];
  category_breakdown: { category: string; sales: number; profit: number; orders: number; margin: number; share: number }[];
  subcategory_performance: { name: string; sales: number; profit: number; orders: number; margin: number }[];
  region_breakdown: { region: string; sales: number; profit: number; orders: number; share: number }[];
  alerts: { type: string; severity: "danger" | "warning" | "info"; title: string; message: string }[];
  generated_at: string;
}

const KPI_ICONS: Record<string, typeof DollarSign> = {
  revenue: DollarSign,
  profit: TrendingUp,
  orders: ShoppingCart,
  customers: Users,
  aov: BarChart3,
  margin: Activity,
};

function formatKpi(kpi: Kpi): string {
  if (kpi.format === "currency") return formatCurrency(kpi.value);
  if (kpi.format === "percent") return formatPercent(kpi.value);
  return formatNumber(kpi.value);
}

function Sparkline({ points, negative }: { points: { value: number }[]; negative: boolean }) {
  if (!points || points.length < 2) return null;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 96;
  const height = 30;
  const coords = values.map((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = negative ? "#9ca3af" : "#111111";

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" style={{ display: "block" }}>
      <polyline
        points={coords.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={width}
        cy={Number(coords[coords.length - 1].split(",")[1])}
        r="2.2"
        fill={color}
      />
    </svg>
  );
}

function KpiCard({ kpi, index }: { kpi: Kpi; index: number }) {
  const Icon = KPI_ICONS[kpi.key] ?? DollarSign;
  const tone = deltaTone(kpi.delta_pct);
  const negative = tone === "negative";
  const deltaColor = tone === "positive" ? "#047857" : tone === "negative" ? "#b91c1c" : "#6b7280";
  const deltaBg = tone === "positive" ? "#ecfdf5" : tone === "negative" ? "#fef2f2" : "#f9fafb";

  return (
    <div
      className="kpi-card animate-fade-up"
      style={{ animationDelay: `${index * 55}ms`, opacity: 0, display: "flex", flexDirection: "column", gap: 10 }}
    >
      <div className="kpi-accent-bar" />
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <span className="kpi-label" style={{ marginBottom: 0 }}>{kpi.label}</span>
        <div className="kpi-icon-box" style={{ width: 30, height: 30 }}>
          <Icon size={14} color="#000000" />
        </div>
      </div>

      <div className="kpi-value" style={{ fontSize: 26, marginBottom: 0 }}>{formatKpi(kpi)}</div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span
          style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            padding: "2px 7px", borderRadius: 999, background: deltaBg,
            color: deltaColor, fontSize: 11, fontWeight: 700,
          }}
          title={`Previous period: ${
            kpi.format === "currency" ? formatCurrency(kpi.previous)
              : kpi.format === "percent" ? formatPercent(kpi.previous)
                : formatNumber(kpi.previous)
          }`}
        >
          {tone === "positive" ? <ArrowUpRight size={11} /> : tone === "negative" ? <ArrowDownRight size={11} /> : null}
          {formatDelta(kpi.delta_pct)}
        </span>
        <Sparkline points={kpi.spark} negative={negative} />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [months, setMonths] = useState(12);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getDashboard(months)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError("");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const message = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        setError(message || "Could not reach the analytics API. Make sure the FastAPI server is running on port 8000.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [months, reloadKey]);

  const refresh = () => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  };

  const chartOptions: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        labels: { color: "#111111", boxWidth: 12, padding: 18, font: { size: 12, weight: 600 } },
      },
      tooltip: {
        backgroundColor: "#000000",
        padding: 12,
        titleFont: { size: 12, weight: 700 },
        bodyFont: { size: 12 },
        callbacks: {
          label: (ctx) => ` ${ctx.dataset.label}: ${formatCurrency(ctx.parsed.y)}`,
        },
      },
    },
    scales: {
      x: {
        ticks: { color: "#6b7280", maxTicksLimit: 12, font: { size: 11 } },
        grid: { color: "#f3f4f6" },
      },
      y: {
        ticks: {
          color: "#6b7280",
          callback: (value) => formatCompact(Number(value)),
          font: { size: 11 },
        },
        grid: { color: "#f3f4f6" },
      },
    },
  };

  const adaptive = data && (data as { mode?: string }).mode === "adaptive"
    ? (data as unknown as AdaptiveModulePayload)
    : null;

  const header = (
    <div className="page-header" style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="page-title">
            <div className="page-title-icon"><LayoutDashboard size={18} /></div>
            Executive Dashboard
          </div>
          <p className="page-subtitle">
            {adaptive
              ? "Business KPIs and outcome comparisons computed from the active dataset."
              : "Trailing 90 days against the previous 90 — computed from the loaded order history."}
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {!adaptive && (
            <select
              value={months}
              onChange={(e) => { setLoading(true); setMonths(Number(e.target.value)); }}
              aria-label="Trend range"
              style={{ fontSize: 12, padding: "7px 10px" }}
            >
              <option value={6}>Last 6 months</option>
              <option value={12}>Last 12 months</option>
              <option value={24}>Last 24 months</option>
            </select>
          )}
          <button className="btn-ghost" onClick={refresh} style={{ fontSize: 12 }}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>
    </div>
  );

  if (loading && !data) {
    return (
      <div>
        {header}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(215px, 1fr))", gap: 14, marginBottom: 16 }}>
          {[...Array(6)].map((_, i) => <div key={i} className="skeleton" style={{ height: 132 }} />)}
        </div>
        <div className="skeleton" style={{ height: 320, marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 220 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "64px 24px" }}>
          <AlertTriangle size={30} color="#b91c1c" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>Dashboard unavailable</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 440, margin: "0 auto 18px" }}>{error}</p>
          <button className="btn-primary" onClick={refresh}><RefreshCw size={14} /> Try again</button>
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

  if (!data?.has_data) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "72px 24px" }}>
          <div style={{
            width: 52, height: 52, borderRadius: 14, background: "#f3f4f6", border: "1px solid var(--border)",
            display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px",
          }}>
            <Upload size={22} color="#111111" />
          </div>
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 6 }}>No dataset loaded</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 420, margin: "0 auto 20px" }}>
            Upload a CSV or Excel export to populate the dashboard. Nothing here is simulated —
            the modules stay empty until real rows exist.
          </p>
          <Link href="/upload" className="btn-primary">Upload data <ArrowUpRight size={14} /></Link>
        </div>
      </div>
    );
  }

  const { meta, period, kpis, revenue_trend, category_breakdown, subcategory_performance, region_breakdown, alerts } = data;

  const chartData = {
    labels: revenue_trend.map((r) => r.month),
    datasets: [
      {
        label: "Revenue",
        data: revenue_trend.map((r) => r.sales),
        borderColor: "#000000",
        backgroundColor: "rgba(0, 0, 0, 0.05)",
        fill: true,
        tension: 0.35,
        pointRadius: 2.5,
        pointHoverRadius: 6,
        borderWidth: 2.5,
      },
      {
        label: "Profit",
        data: revenue_trend.map((r) => r.profit),
        borderColor: "#6b7280",
        backgroundColor: "rgba(107, 114, 128, 0.04)",
        fill: true,
        tension: 0.35,
        pointRadius: 2.5,
        pointHoverRadius: 6,
        borderWidth: 2,
        borderDash: [5, 4],
      },
    ],
  };

  return (
    <div>
      {header}

      {/* Dataset context */}
      <div
        className="panel animate-fade-up"
        style={{
          padding: "11px 16px", marginBottom: 16, opacity: 0,
          display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
          fontSize: 11.5, color: "var(--text-secondary)",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontWeight: 700, color: "#111111" }}>
          <CheckCircle2 size={13} /> {meta?.org_name || meta?.dataset_name || "Dataset"}
        </span>
        <span>{formatNumber(meta?.rows)} rows · {formatNumber(meta?.customers)} customers · {formatNumber(meta?.orders)} orders</span>
        <span>{meta?.date_from} → {meta?.date_to}</span>
        <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#10b981" }} />
          Window {period?.current_from} → {period?.current_to}
        </span>
      </div>

      {/* KPI cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(215px, 1fr))", gap: 14, marginBottom: 16 }}>
        {kpis.map((kpi, index) => <KpiCard key={kpi.key} kpi={kpi} index={index} />)}
      </div>

      {/* Trend + alerts */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 14 }}>
        <div className="chart-panel animate-fade-up" style={{ flex: "1 1 560px", minWidth: 0, animationDelay: "300ms", opacity: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 8 }}>
            <div>
              <div className="chart-title">Revenue &amp; profit trend</div>
              <div className="chart-subtitle">Monthly totals across the selected range</div>
            </div>
            <span className="tag tag-info">{formatNumber(revenue_trend.reduce((sum, r) => sum + r.orders, 0))} orders in range</span>
          </div>
          <div style={{ height: 290 }}>
            {revenue_trend.length > 0
              ? <Line data={chartData} options={chartOptions} />
              : <div style={{ display: "grid", placeItems: "center", height: "100%", color: "var(--text-muted)", fontSize: 12 }}>Not enough history to plot</div>}
          </div>
        </div>

        <div className="panel panel-body animate-fade-up" style={{ flex: "0 1 330px", minWidth: 260, animationDelay: "340ms", opacity: 0 }}>
          <div className="panel-header" style={{ marginBottom: 12 }}>
            <span className="panel-title" style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
              <AlertTriangle size={15} /> Alerts
            </span>
            <span className={`tag ${alerts.length ? "tag-warning" : "tag-success"}`}>{alerts.length} active</span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {alerts.length === 0 && (
              <div className="alert-item alert-info" style={{ display: "flex", gap: 9 }}>
                <CheckCircle2 size={14} style={{ marginTop: 2, flexShrink: 0 }} />
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700 }}>All clear</div>
                  <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                    No margin, momentum, drift or concentration signals crossed their thresholds.
                  </p>
                </div>
              </div>
            )}

            {alerts.map((alert, index) => {
              const isDanger = alert.severity === "danger";
              const isWarning = alert.severity === "warning";
              return (
                <div
                  key={`${alert.type}-${index}`}
                  className={`alert-item ${isDanger ? "alert-danger" : isWarning ? "alert-warning" : "alert-info"}`}
                >
                  {isDanger || isWarning
                    ? <AlertTriangle size={14} style={{ color: isDanger ? "#b91c1c" : "#b45309", marginTop: 2, flexShrink: 0 }} />
                    : <Info size={14} style={{ color: "#111111", marginTop: 2, flexShrink: 0 }} />}
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#111111", marginBottom: 2 }}>{alert.title}</div>
                    <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>{alert.message}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Category + region */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 14 }}>
        <div className="panel panel-body animate-fade-up" style={{ flex: "1 1 520px", minWidth: 0, animationDelay: "380ms", opacity: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Category performance</span>
            <span className="tag tag-info">{category_breakdown.length} categories</span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 15 }}>
            {category_breakdown.map((cat) => {
              const marginTag = cat.margin >= 15 ? "tag-success" : cat.margin >= 5 ? "tag-warning" : "tag-danger";
              return (
                <div key={cat.category}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6, gap: 10 }}>
                    <span style={{ fontSize: 13, fontWeight: 700 }}>{cat.category}</span>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span className={`tag ${marginTag}`}>{formatPercent(cat.margin)} margin</span>
                      <span style={{ fontSize: 12, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{formatCurrency(cat.sales)}</span>
                      <span style={{ fontSize: 11, color: "var(--text-muted)", minWidth: 34, textAlign: "right" }}>{formatPercent(cat.share)}</span>
                    </div>
                  </div>
                  <div className="progress-track">
                    <div
                      className="progress-fill"
                      style={{ width: `${cat.share}%`, background: cat.margin < 5 ? "#9ca3af" : "#000000" }}
                    />
                  </div>
                  <div style={{ display: "flex", gap: 14, marginTop: 5, fontSize: 10.5, color: "var(--text-muted)" }}>
                    <span>{formatNumber(cat.orders)} orders</span>
                    <span>Profit {formatCurrency(cat.profit)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="panel panel-body animate-fade-up" style={{ flex: "0 1 310px", minWidth: 250, animationDelay: "420ms", opacity: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Revenue by region</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {region_breakdown.map((region) => (
              <div key={region.region}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 12 }}>
                  <span style={{ fontWeight: 600 }}>{region.region}</span>
                  <span style={{ color: "var(--text-muted)" }}>
                    {formatCurrency(region.sales)} · {formatPercent(region.share)}
                  </span>
                </div>
                <div className="progress-track" style={{ height: 5 }}>
                  <div className="progress-fill" style={{ width: `${region.share}%`, background: "#4b5563" }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Sub-category table */}
      <div className="panel animate-fade-up" style={{ animationDelay: "460ms", opacity: 0 }}>
        <div className="panel-body" style={{ paddingBottom: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Top sub-categories</span>
            <span className="tag tag-info">Ranked by revenue</span>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Sub-category</th>
                <th style={{ textAlign: "right" }}>Revenue</th>
                <th style={{ textAlign: "right" }}>Profit</th>
                <th style={{ textAlign: "right" }}>Margin</th>
                <th style={{ textAlign: "right" }}>Orders</th>
              </tr>
            </thead>
            <tbody>
              {subcategory_performance.map((row) => {
                const marginTag = row.margin >= 15 ? "tag-success" : row.margin >= 5 ? "tag-warning" : "tag-danger";
                return (
                  <tr key={row.name}>
                    <td className="td-primary">{row.name}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(row.sales)}</td>
                    <td className="td-num" style={{ textAlign: "right", color: row.profit < 0 ? "#b91c1c" : undefined }}>
                      {formatCurrency(row.profit)}
                    </td>
                    <td style={{ textAlign: "right" }}><span className={`tag ${marginTag}`}>{formatPercent(row.margin)}</span></td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatNumber(row.orders)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{ padding: "10px 16px", fontSize: 10.5, color: "var(--text-muted)", borderTop: "1px solid var(--border-subtle)" }}>
          Computed {new Date(data.generated_at).toLocaleString()} · {formatNumber(meta?.rows)} order lines · source: {meta?.source}
        </div>
      </div>
    </div>
  );
}
