"use client";
import { useState, useEffect } from "react";
import {
  FileBarChart2, Building2, Activity, TrendingUp, TrendingDown,
  AlertTriangle, CheckCircle2, Zap, Users, ShoppingCart,
  DollarSign, Target, ArrowRight, RefreshCw, Info, BarChart3,
  Layers, ArrowUpRight, ShieldAlert,
} from "lucide-react";
import { getAnalysisReport } from "@/lib/api";
import AdaptiveReport, { type AdaptiveReportData } from "@/components/AdaptiveReport";
import ReportExportButtons from "@/components/ReportExportButtons";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Cell, PieChart, Pie, Legend,
  ReferenceLine, Area, AreaChart,
} from "recharts";

// ─── Types ────────────────────────────────────────────────────────────────────
interface KpiEntry {
  value: number; baseline: number; target: number; unit: string;
}
interface SegmentEntry {
  segment: string; customer_count: number; avg_spend: number;
  avg_frequency: number; avg_recency_days: number;
}
interface DriftPoint {
  month: string; revenue: number; profit: number; orders: number;
  customers: number; aov: number; margin_pct: number;
}
interface AnomalyPoint {
  date: string; value: number; z_score: number; type: string;
}
interface FishboneCause {
  factor: string; confidence: number; evidence: string;
}
interface ForecastPoint {
  month: string; predicted: number; lower: number; upper: number;
}
interface BenchmarkEntry {
  metric: string; org_value: number; benchmark_low: number;
  benchmark_high: number; unit: string;
}
interface ActionItem {
  priority: number; area: string; action: string; impact: string; effort: string;
}
interface AnalysisData {
  compatible?: boolean;
  mode?: string;
  dataset_type?: string;
  message?: string;
  org: {
    org_name: string | null; dataset_name: string; uploaded_at: string | null;
    row_count: number; customer_count: number; total_sales: number;
    date_from: string | null; date_to: string | null;
  };
  health_score: number;
  kpis: Record<string, KpiEntry>;
  segmentation: SegmentEntry[];
  drift_series: DriftPoint[];
  anomalies: AnomalyPoint[];
  root_cause: {
    fishbone: Record<string, FishboneCause[]>;
    top_root_cause: { branch: string; factor: string; confidence: number; evidence: string };
    anomaly_months: string[];
  };
  forecast: ForecastPoint[];
  benchmarks: BenchmarkEntry[];
  action_items: ActionItem[];
  generated_at: string;
}

// ─── Design Tokens ────────────────────────────────────────────────────────────
const SEGMENT_COLORS: Record<string, string> = {
  Champions: "#000000", Loyal: "#374151", "New": "#6b7280",
  "At-Risk": "#9ca3af", Lost: "#d1d5db", Potential: "#4b5563",
};

function healthStatus(score: number) {
  if (score >= 75) return { label: "Excellent",  color: "#059669", bg: "#ecfdf5" };
  if (score >= 55) return { label: "Good",       color: "#2563eb", bg: "#eff6ff" };
  if (score >= 35) return { label: "Warning",    color: "#d97706", bg: "#fffbeb" };
  return             { label: "Critical",  color: "#dc2626", bg: "#fef2f2" };
}

function pctChange(val: number, base: number): { pct: string; positive: boolean } {
  if (!base) return { pct: "—", positive: true };
  const p = ((val - base) / Math.abs(base)) * 100;
  return { pct: `${p >= 0 ? "+" : ""}${p.toFixed(1)}%`, positive: p >= 0 };
}

function fmt(val: number, unit: string): string {
  if (unit === "USD") {
    if (val >= 1_000_000) return `$${(val / 1_000_000).toFixed(1)}M`;
    if (val >= 1_000)     return `$${(val / 1_000).toFixed(1)}K`;
    return `$${val.toLocaleString()}`;
  }
  if (unit === "%") return `${val.toFixed(1)}%`;
  if (val >= 1_000) return val.toLocaleString();
  return String(val);
}

// ─── Subcomponents ────────────────────────────────────────────────────────────
function SectionTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8,
          background: "#000000", color: "#ffffff",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>{icon}</div>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: "var(--text-primary)", letterSpacing: -0.3 }}>{title}</h2>
      </div>
      {subtitle && <p style={{ margin: "0 0 0 42px", fontSize: 12.5, color: "var(--text-secondary)" }}>{subtitle}</p>}
    </div>
  );
}

function KpiCard({ label, data, icon }: { label: string; data: KpiEntry; icon: React.ReactNode }) {
  const { pct, positive } = pctChange(data.value, data.baseline);
  const targetPct = data.target > 0 ? Math.min(100, (data.value / data.target) * 100) : 0;
  return (
    <div style={{
      background: "var(--bg-surface)", border: "1px solid var(--border)",
      borderRadius: 12, padding: "18px 20px",
      display: "flex", flexDirection: "column", gap: 10,
      boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
        <div style={{ color: "#111111" }}>{icon}</div>
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color: "#000000", letterSpacing: -1 }}>
        {fmt(data.value, data.unit)}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {positive
          ? <TrendingUp size={13} color="#059669" />
          : <TrendingDown size={13} color="#dc2626" />}
        <span style={{ fontSize: 12.5, fontWeight: 700, color: positive ? "#059669" : "#dc2626" }}>{pct}</span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>vs baseline</span>
      </div>
      {/* Progress to target */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
          <span style={{ fontSize: 10.5, color: "var(--text-muted)", fontWeight: 500 }}>Target progress</span>
          <span style={{ fontSize: 10.5, color: "var(--text-secondary)", fontWeight: 600 }}>{fmt(data.target, data.unit)}</span>
        </div>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${targetPct}%`, background: "#000000" }} />
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────
function apiErrorMessage(error: unknown): string {
  const response = (error as { response?: { data?: unknown } })?.response?.data;
  if (typeof response === "string") return response;
  const detail = (response as { detail?: unknown })?.detail;
  return typeof detail === "string" ? detail : "Failed to load analysis. Please upload a dataset first.";
}

export default function AnalysisPage() {
  const [data, setData] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeKpi, setActiveKpi] = useState("revenue");

  const load = () => {
    setLoading(true); setError("");
    getAnalysisReport()
      .then((payload) => { setData(payload); setLoading(false); })
      .catch((requestError: unknown) => {
        setError(apiErrorMessage(requestError));
        setLoading(false);
      });
  };

  useEffect(() => {
    let cancelled = false;
    getAnalysisReport()
      .then((payload) => { if (!cancelled) setData(payload); })
      .catch((requestError: unknown) => { if (!cancelled) setError(apiErrorMessage(requestError)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "60vh", flexDirection: "column", gap: 16 }}>
      <div style={{ width: 44, height: 44, border: "3px solid #e5e7eb", borderTopColor: "#000000", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      <div style={{ fontSize: 14, color: "var(--text-secondary)", fontWeight: 500 }}>Computing organizational intelligence…</div>
    </div>
  );

  if (error) return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh", gap: 16, textAlign: "center" }}>
      <AlertTriangle size={36} color="#dc2626" />
      <div style={{ fontSize: 18, color: "#000000", fontWeight: 700 }}>Analysis Unavailable</div>
      <div style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 460, lineHeight: 1.6 }}>{error}</div>
      <a href="/upload" className="btn-primary" style={{ marginTop: 8 }}>Upload Dataset <ArrowRight size={14} /></a>
    </div>
  );

  if (!data) return null;

  // Non-sales datasets get the adaptive report: profiling, EDA and the task
  // the data actually supports (never sales metrics).
  if (data.mode === "adaptive") {
    return (
      <AdaptiveReport
        report={data as unknown as AdaptiveReportData}
        onRefresh={load}
      />
    );
  }

  // ── Incompatible Dataset Screen (e.g. Telecom Customer Churn) ───────────────
  if (data.compatible === false) {
    const org = data.org;
    return (
      <div>
        <div className="page-header">
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
            <div>
              <div className="page-title">
                <div className="page-title-icon">
                  <FileBarChart2 size={18} />
                </div>
                Analysis Report
              </div>
              <p className="page-subtitle">
                Deep organizational intelligence and sales revenue audit.
              </p>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <ReportExportButtons />
              <button id="refresh-analysis" className="btn-ghost" onClick={load} style={{ fontSize: 12, gap: 6 }}>
                <RefreshCw size={13} /> Refresh
              </button>
            </div>
          </div>
        </div>

        {/* Dataset Meta Banner */}
        <div className="panel panel-body animate-fade-up" style={{ marginBottom: 20, opacity: 0, background: "#ffffff", border: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div style={{ width: 48, height: 48, borderRadius: 12, background: "#000000", color: "#ffffff", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <Building2 size={22} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: "#000000", letterSpacing: -0.5 }}>
                {org.org_name || "Your Organization"}
              </div>
              <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginTop: 2 }}>
                {org.dataset_name} · {org.row_count?.toLocaleString()} subscriber records · Customer Churn Analysis
              </div>
            </div>
            {org.uploaded_at && (
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Loaded At</div>
                <div style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 600 }}>
                  {new Date(org.uploaded_at).toLocaleString()}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Compatibility Notice Panel */}
        <div className="panel panel-body animate-fade-up" style={{ marginBottom: 24, padding: "32px", border: "1px solid #fed7aa", background: "#fffaf5" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 18 }}>
            <div style={{ width: 44, height: 44, borderRadius: 10, background: "#ffedd5", color: "#ea580c", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <ShieldAlert size={24} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 6 }}>
                <span style={{ fontSize: 17, fontWeight: 800, color: "#9a3412" }}>
                  Sales Analysis Report Incompatible with Churn Data
                </span>
                <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#ffedd5", color: "#c2410c", border: "1px solid #fed7aa" }}>
                  Telecom Customer Churn
                </span>
              </div>
              <p style={{ fontSize: 13, color: "#7c2d12", lineHeight: 1.65, marginBottom: 16 }}>
                {data.message || (
                  "The BIDS Analysis Report calculates deep sales transaction intelligence: multi-period revenue drift, product profit margins, order velocity, repeat purchase rates, and revenue drop root-cause fishbone diagrams. Because churn datasets contain subscriber tenure, call minutes, usage charges, and churn status rather than transactional sales orders, BIDS preserves your analytical truthfulness by not fabricating fake sales dates or profit margins."
                )}
              </p>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#9a3412", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>
                Recommended Modules for Churn Analysis
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
                <a
                  href="/behavior"
                  style={{
                    display: "block",
                    padding: "14px 16px",
                    borderRadius: 8,
                    background: "#ffffff",
                    border: "1px solid #fed7aa",
                    textDecoration: "none",
                    color: "inherit",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                    <span style={{ fontSize: 13.5, fontWeight: 700, color: "#000000" }}>Customer Behavior</span>
                    <ArrowUpRight size={14} color="#ea580c" />
                  </div>
                  <p style={{ fontSize: 12, color: "var(--text-secondary)", margin: 0, lineHeight: 1.45 }}>
                    Inspect subscriber activity, calling cadence, usage intensity, and engagement cohorts.
                  </p>
                </a>
                <a
                  href="/segmentation"
                  style={{
                    display: "block",
                    padding: "14px 16px",
                    borderRadius: 8,
                    background: "#ffffff",
                    border: "1px solid #fed7aa",
                    textDecoration: "none",
                    color: "inherit",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                    <span style={{ fontSize: 13.5, fontWeight: 700, color: "#000000" }}>Customer Segmentation</span>
                    <ArrowUpRight size={14} color="#ea580c" />
                  </div>
                  <p style={{ fontSize: 12, color: "var(--text-secondary)", margin: 0, lineHeight: 1.45 }}>
                    Explore active vs. churned subscriber breakdown, geographical clusters, and account tiers.
                  </p>
                </a>
                <a
                  href="/upload"
                  style={{
                    display: "block",
                    padding: "14px 16px",
                    borderRadius: 8,
                    background: "#ffffff",
                    border: "1px solid #fed7aa",
                    textDecoration: "none",
                    color: "inherit",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                    <span style={{ fontSize: 13.5, fontWeight: 700, color: "#000000" }}>Upload Sales Dataset</span>
                    <ArrowUpRight size={14} color="#ea580c" />
                  </div>
                  <p style={{ fontSize: 12, color: "var(--text-secondary)", margin: 0, lineHeight: 1.45 }}>
                    Upload e-commerce or retail transactions to generate the complete deep sales intelligence report.
                  </p>
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const hs = healthStatus(data.health_score);
  const { org, kpis, segmentation, drift_series, anomalies, root_cause, forecast, benchmarks, action_items } = data;

  const kpiCards = [
    { key: "total_revenue",     label: "Total Revenue",     icon: <DollarSign size={14} />,  driftKey: "revenue" },
    { key: "total_profit",      label: "Total Profit",      icon: <TrendingUp size={14} />,  driftKey: "profit" },
    { key: "total_orders",      label: "Orders",            icon: <ShoppingCart size={14} />, driftKey: "orders" },
    { key: "unique_customers",  label: "Customers",         icon: <Users size={14} />,        driftKey: "customers" },
    { key: "avg_order_value",   label: "Avg Order Value",   icon: <Activity size={14} />,    driftKey: "aov" },
    { key: "profit_margin_pct", label: "Profit Margin",     icon: <Target size={14} />,       driftKey: "margin_pct" },
  ];

  const driftDataWithAnomalies = drift_series.map((d) => ({
    ...d,
    isAnomaly: anomalies.some((a) => a.date === d.month),
  }));

  const activeDriftKey = kpiCards.find(k => k.key === activeKpi)?.driftKey || "revenue";

  return (
    <div>
      {/* ── Header ──────────────────────────────────────────────────────────────── */}
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div>
            <div className="page-title">
              <div className="page-title-icon">
                <FileBarChart2 size={18} />
              </div>
              Analysis Report
            </div>
            <p className="page-subtitle">
              Deep organizational intelligence — every number computed from your uploaded dataset.
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <ReportExportButtons />
            <button id="refresh-analysis" className="btn-ghost" onClick={load} style={{ fontSize: 12, gap: 6 }}>
              <RefreshCw size={13} /> Refresh
            </button>
          </div>
        </div>
      </div>

      {/* ── 1. Org Identity Banner ──────────────────────────────────────────────── */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 20, opacity: 0, background: "#ffffff", border: "1px solid var(--border)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <div style={{ width: 48, height: 48, borderRadius: 12, background: "#000000", color: "#ffffff", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <Building2 size={22} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#000000", letterSpacing: -0.5 }}>
              {org.org_name || "Your Organization"}
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginTop: 2 }}>
              {org.dataset_name} · {org.row_count?.toLocaleString()} orders · {org.customer_count?.toLocaleString()} customers
              {org.date_from && ` · ${org.date_from} → ${org.date_to}`}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Generated</div>
            <div style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 600 }}>
              {new Date(data.generated_at).toLocaleString()}
            </div>
          </div>
        </div>
      </div>

      {/* ── 2. Health Score Gauge ───────────────────────────────────────────────── */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 20, opacity: 0, display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
        <div style={{ position: "relative", width: 100, height: 100, flexShrink: 0 }}>
          <svg width="100" height="100" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="42" fill="none" stroke="#e5e7eb" strokeWidth="10" />
            <circle cx="50" cy="50" r="42" fill="none" stroke={hs.color} strokeWidth="10"
              strokeDasharray={`${(data.health_score / 100) * 2 * Math.PI * 42} ${2 * Math.PI * 42}`}
              strokeDashoffset={2 * Math.PI * 42 * 0.25}
              strokeLinecap="round"
              style={{ transition: "stroke-dasharray 1s ease" }}
            />
          </svg>
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
            <div style={{ fontSize: 22, fontWeight: 800, color: "#000000", letterSpacing: -1 }}>{data.health_score}</div>
            <div style={{ fontSize: 9, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase" }}>/ 100</div>
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4, fontWeight: 700 }}>Organization Health Score</div>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "4px 14px", borderRadius: 20, background: hs.bg, border: `1px solid ${hs.color}40`, marginBottom: 10 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: hs.color }} />
            <span style={{ fontSize: 14, fontWeight: 700, color: hs.color }}>{hs.label}</span>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--text-secondary)", maxWidth: 420, lineHeight: 1.5 }}>
            Composite score based on revenue trend, profit margins, customer health, and anomaly frequency — all derived from your dataset.
          </div>
        </div>
        {/* Score breakdown pills */}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
          {[
            { label: "Revenue",  val: kpis.total_revenue?.value,       base: kpis.total_revenue?.baseline,       unit: "USD" },
            { label: "Margin",   val: kpis.profit_margin_pct?.value,   base: kpis.profit_margin_pct?.baseline,   unit: "%" },
            { label: "Repeat",   val: kpis.repeat_rate_pct?.value,     base: kpis.repeat_rate_pct?.baseline,     unit: "%" },
          ].map(({ label, val, base, unit }) => {
            if (!val) return null;
            const { pct, positive } = pctChange(val, base);
            return (
              <div key={label} style={{ textAlign: "center", padding: "8px 14px", background: "#f9fafb", borderRadius: 8, border: "1px solid var(--border)" }}>
                <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 2, fontWeight: 600 }}>{label}</div>
                <div style={{ fontSize: 14, fontWeight: 800, color: "#000000" }}>{fmt(val, unit)}</div>
                <div style={{ fontSize: 10.5, color: positive ? "#059669" : "#dc2626", fontWeight: 700 }}>{pct}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── 3. KPI Grid ────────────────────────────────────────────────────────── */}
      <div className="animate-fade-up" style={{ opacity: 0, marginBottom: 20 }}>
        <SectionTitle icon={<Activity size={16} />} title="Executive KPI Summary" subtitle="Current period vs baseline (first-half) and target" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }}>
          {kpiCards.map(({ key, label, icon }) => kpis[key] ? (
            <div key={key} style={{ cursor: "pointer" }} onClick={() => setActiveKpi(key)}>
              <KpiCard label={label} data={kpis[key]} icon={icon} />
            </div>
          ) : null)}
        </div>
      </div>

      {/* ── 4. Benchmark Comparison ─────────────────────────────────────────────── */}
      {benchmarks.length > 0 && (
        <div className="panel animate-fade-up" style={{ marginBottom: 20, opacity: 0, overflow: "hidden" }}>
          <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
            <SectionTitle icon={<Target size={16} />} title="Where You Stand" subtitle="Your metrics vs data-derived benchmark ranges" />
          </div>
          <div style={{ padding: "0 20px 20px" }}>
            {benchmarks.map((b) => {
              const range = b.benchmark_high - b.benchmark_low;
              const pos = range > 0 ? Math.min(100, Math.max(0, (b.org_value - b.benchmark_low) / range * 100)) : 50;
              const aboveHigh = b.org_value > b.benchmark_high;
              const belowLow  = b.org_value < b.benchmark_low;
              return (
                <div key={b.metric} style={{ marginTop: 18 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{b.metric}</span>
                    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                      <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>Benchmark: {fmt(b.benchmark_low, b.unit)} – {fmt(b.benchmark_high, b.unit)}</span>
                      <span style={{ fontSize: 13, fontWeight: 800, color: aboveHigh ? "#059669" : belowLow ? "#dc2626" : "#000000" }}>
                        {fmt(b.org_value, b.unit)}
                      </span>
                    </div>
                  </div>
                  <div style={{ position: "relative", height: 8, background: "#e5e7eb", borderRadius: 4 }}>
                    <div style={{ position: "absolute", left: 0, right: 0, height: "100%", background: "#d1d5db", borderRadius: 4 }} />
                    <div style={{ position: "absolute", left: `${pos}%`, top: -3, width: 14, height: 14, borderRadius: "50%", background: "#000000", border: "2px solid #ffffff", transform: "translateX(-50%)", transition: "left 0.6s ease" }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── 5. Segmentation Breakdown ────────────────────────────────────────────── */}
      {segmentation.length > 0 && (
        <div className="panel animate-fade-up" style={{ marginBottom: 20, opacity: 0 }}>
          <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
            <SectionTitle icon={<Users size={16} />} title="Customer Segmentation" subtitle="RFM-based cluster analysis of your customer base" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 0 }}>
            <div style={{ borderRight: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={segmentation} dataKey="customer_count" nameKey="segment" cx="50%" cy="50%" outerRadius={80} innerRadius={45}>
                    {segmentation.map((s) => (
                      <Cell key={s.segment} fill={SEGMENT_COLORS[s.segment] || "#000000"} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v: unknown) => [`${v} customers`]} contentStyle={{ background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: 8, color: "#000000" }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div style={{ padding: 20, overflowX: "auto" }}>
              <table className="data-table" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>Segment</th><th>Customers</th><th>Avg Spend</th><th>Avg Orders</th><th>Recency (days)</th>
                  </tr>
                </thead>
                <tbody>
                  {segmentation.map((s) => (
                    <tr key={s.segment}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div style={{ width: 8, height: 8, borderRadius: "50%", background: SEGMENT_COLORS[s.segment] || "#000000", flexShrink: 0 }} />
                          <span style={{ fontWeight: 700, color: "#000000" }}>{s.segment}</span>
                        </div>
                      </td>
                      <td style={{ fontWeight: 700 }}>{s.customer_count.toLocaleString()}</td>
                      <td>${s.avg_spend.toLocaleString()}</td>
                      <td>{s.avg_frequency.toFixed(1)}</td>
                      <td>{s.avg_recency_days.toFixed(0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── 6. Drift Timeline ───────────────────────────────────────────────────── */}
      {drift_series.length > 0 && (
        <div className="panel animate-fade-up" style={{ marginBottom: 20, opacity: 0, overflow: "hidden" }}>
          <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <SectionTitle icon={<Activity size={16} />} title="Data Drift Timeline" subtitle="Monthly KPI series with anomaly markers" />
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {kpiCards.map(({ key, label }) => (
                <button
                  key={key}
                  id={`drift-toggle-${key}`}
                  onClick={() => setActiveKpi(key)}
                  style={{
                    fontSize: 11, padding: "5px 12px", borderRadius: 6, cursor: "pointer",
                    border: `1px solid ${activeKpi === key ? "#000000" : "var(--border)"}`,
                    background: activeKpi === key ? "#000000" : "#ffffff",
                    color: activeKpi === key ? "#ffffff" : "var(--text-secondary)",
                    fontWeight: activeKpi === key ? 700 : 500,
                  }}
                >{label}</button>
              ))}
            </div>
          </div>
          <div style={{ padding: "20px 20px 10px" }}>
            {anomalies.length > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14, fontSize: 11.5, color: "#dc2626", fontWeight: 600 }}>
                <AlertTriangle size={14} /> {anomalies.length} anomal{anomalies.length === 1 ? "y" : "ies"} detected (red markers)
              </div>
            )}
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={driftDataWithAnomalies} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="driftGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#000000" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#000000" stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#6b7280" }} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: "#6b7280" }} tickLine={false} axisLine={false} width={55} tickFormatter={(v: number) => {
                  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
                  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
                  return `${v}`;
                }} />
                <Tooltip
                  contentStyle={{ background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: 8, fontSize: 12, color: "#000000" }}
                  formatter={(v: unknown) => [v != null ? Number(v).toLocaleString() : ""]}
                />
                {anomalies.map((a) => (
                  <ReferenceLine key={a.date} x={a.date} stroke="#dc2626" strokeDasharray="4 4" strokeWidth={1.5}
                    label={{ value: "!", position: "top", fill: "#dc2626", fontSize: 11 }}
                  />
                ))}
                <Area type="monotone" dataKey={activeDriftKey} stroke="#000000" strokeWidth={2} fill="url(#driftGrad)" dot={false} activeDot={{ r: 4, fill: "#000000" }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── 7. Root Cause Fishbone ──────────────────────────────────────────────── */}
      <div className="panel animate-fade-up" style={{ marginBottom: 20, opacity: 0, overflow: "hidden" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
          <SectionTitle icon={<AlertTriangle size={16} />} title="Root Cause Analysis" subtitle="Causal factor confidence scores computed from real data patterns" />
          {root_cause.top_root_cause?.factor && (
            <div style={{ marginTop: 10, padding: "12px 16px", background: "#fef2f2", border: "1px solid #fecaca", borderLeft: "4px solid #dc2626", borderRadius: 8 }}>
              <div style={{ fontSize: 11, color: "#dc2626", fontWeight: 800, marginBottom: 3 }}>
                TOP ROOT CAUSE · {root_cause.top_root_cause.branch.toUpperCase()}
              </div>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: "#111111", marginBottom: 2 }}>
                {root_cause.top_root_cause.factor} — {(root_cause.top_root_cause.confidence * 100).toFixed(0)}% confidence
              </div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{root_cause.top_root_cause.evidence}</div>
            </div>
          )}
        </div>
        <div style={{ padding: 20 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
            {Object.entries(root_cause.fishbone || {}).map(([branch, causes]) => (
              <div key={branch} style={{ background: "#f9fafb", borderRadius: 10, overflow: "hidden", border: "1px solid var(--border)" }}>
                <div style={{ padding: "10px 14px", background: "#000000", color: "#ffffff" }}>
                  <span style={{ fontSize: 12, fontWeight: 800 }}>{branch}</span>
                </div>
                <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 10 }}>
                  {causes.map((c) => (
                    <div key={c.factor}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                        <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-primary)" }}>{c.factor}</span>
                        <span style={{ fontSize: 11, fontWeight: 800, color: c.confidence > 0.6 ? "#dc2626" : c.confidence > 0.4 ? "#d97706" : "#4b5563" }}>
                          {(c.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="progress-track" style={{ marginBottom: 5 }}>
                        <div className="progress-fill" style={{ width: `${c.confidence * 100}%`, background: "#000000" }} />
                      </div>
                      <div style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>{c.evidence}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── 8. 6-Month Forecast ─────────────────────────────────────────────────── */}
      {forecast.length > 0 && (
        <div className="panel animate-fade-up" style={{ marginBottom: 20, opacity: 0, overflow: "hidden" }}>
          <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
            <SectionTitle icon={<TrendingUp size={16} />} title="6-Month Revenue Forecast" subtitle="Linear trend projection from historical monthly data" />
          </div>
          <div style={{ padding: "20px 20px 10px" }}>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={[
                ...drift_series.slice(-6).map(d => ({ month: d.month, actual: d.revenue, projected: null, lower: null, upper: null })),
                ...forecast.map(f => ({ month: f.month, actual: null, projected: f.predicted, lower: f.lower, upper: f.upper })),
              ]} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="forecastGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#4b5563" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#4b5563" stopOpacity={0.01} />
                  </linearGradient>
                  <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#000000" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#000000" stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#6b7280" }} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: "#6b7280" }} tickLine={false} axisLine={false} width={55} tickFormatter={(v: number) => v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1_000 ? `${(v / 1_000).toFixed(0)}K` : `${v}`} />
                <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: 8, fontSize: 12, color: "#000000" }} formatter={(v: unknown) => v != null ? [`$${Number(v).toLocaleString()}`] : ["-"]} />
                <Area type="monotone" dataKey="actual"    stroke="#000000" strokeWidth={2} fill="url(#actualGrad)"   dot={false} connectNulls />
                <Area type="monotone" dataKey="projected" stroke="#4b5563" strokeWidth={2} fill="url(#forecastGrad)" dot={false} strokeDasharray="5 4" connectNulls />
                <Area type="monotone" dataKey="upper"     stroke="transparent" fill="rgba(0,0,0,0.03)" fillOpacity={1} connectNulls dot={false} />
              </AreaChart>
            </ResponsiveContainer>
            <div style={{ display: "flex", gap: 20, marginTop: 10, justifyContent: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}><div style={{ width: 18, height: 2, background: "#000000" }} /><span style={{ fontSize: 11.5, color: "var(--text-muted)", fontWeight: 600 }}>Historical</span></div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}><div style={{ width: 18, height: 2, background: "#4b5563", borderTop: "2px dashed #4b5563" }} /><span style={{ fontSize: 11.5, color: "var(--text-muted)", fontWeight: 600 }}>Forecast</span></div>
            </div>
          </div>
        </div>
      )}

      {/* ── 9. Priority Action Table ───────────────────────────────────────────── */}
      {action_items.length > 0 && (
        <div className="panel animate-fade-up" style={{ marginBottom: 20, opacity: 0, overflow: "hidden" }}>
          <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
            <SectionTitle icon={<Zap size={16} />} title="Priority Action Plan" subtitle="Ranked recommendations derived from your data analysis" />
          </div>
          <div style={{ padding: 20 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {action_items.map((item) => {
                const impactColor = item.impact === "High" ? "#dc2626" : item.impact === "Medium" ? "#d97706" : "#4b5563";
                return (
                  <div key={item.priority} style={{
                    display: "flex", alignItems: "flex-start", gap: 14,
                    padding: "14px 16px", background: "#f9fafb", borderRadius: 10,
                    border: "1px solid var(--border)",
                  }}>
                    <div style={{ width: 28, height: 28, borderRadius: 8, background: "#000000", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      <span style={{ fontSize: 12, fontWeight: 800, color: "#ffffff" }}>#{item.priority}</span>
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>{item.area}</div>
                      <div style={{ fontSize: 13, color: "var(--text-primary)", lineHeight: 1.6, fontWeight: 600 }}>{item.action}</div>
                    </div>
                    <div style={{ display: "flex", gap: 6, flexShrink: 0, flexWrap: "wrap", justifyContent: "flex-end" }}>
                      <span style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "#fef2f2", color: impactColor, fontWeight: 700, border: `1px solid ${impactColor}30` }}>
                        {item.impact} Impact
                      </span>
                      <span style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "#f3f4f6", color: "var(--text-secondary)", border: "1px solid var(--border)", fontWeight: 600 }}>
                        {item.effort} Effort
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Bottom note */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 0 24px", fontSize: 11.5, color: "var(--text-muted)" }}>
        <Info size={13} />
        All figures are computed dynamically from your uploaded dataset. Re-upload to refresh the analysis with new data.
      </div>
    </div>
  );
}
