"use client";
import { useEffect, useState } from "react";
import {
  Activity, AlertTriangle, BarChart3, CheckCircle2, Cpu, Edit3,
  Layers, RefreshCw, Save, TrendingUp,
} from "lucide-react";
import { getDrift, patchRule } from "@/lib/api";
import AdaptiveModule, { type AdaptiveModulePayload } from "@/components/AdaptiveModule";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";

type Status = "shifted" | "watch" | "stable";

interface DriftKpi {
  kpi: string;
  column: string;
  unit: string;
  format: string;
  months: string[];
  series: number[];
  current: number;
  baseline: number;
  mean: number;
  std: number;
  volatility_pct: number;
  trend_pct: number;
  latest_delta_pct: number | null;
  level_pct: number | null;
  volatility_change_pp: number;
  direction: "rising" | "falling" | "flat";
  psi: number | null;
  psi_label: string;
  status: Status;
  drift_detected: boolean;
  drift_score: number;
  n_drift_events: number;
  mean_before: number;
  mean_after: number;
  magnitude_pct: number;
  drift_points: { index: number; month: string; value: number; delta_pct: number | null }[];
}

interface KpiTarget {
  kpi_name: string;
  current_value: number;
  baseline_value: number;
  target_value: number;
  drift_score: number;
  unit: string;
  gap_pct: number | null;
  on_target: boolean;
  last_updated: string | null;
}

interface FeatureDrift {
  feature: string;
  key: string;
  kind: "categorical" | "numeric";
  psi: number;
  status: "stable" | "moderate" | "significant";
  method: string;
  distribution: { band: string; baseline: number; recent: number }[];
  summary: string;
  baseline_window: string;
  recent_window: string;
}

interface RuleEvaluation {
  metric: string | null;
  label: string | null;
  unit: string | null;
  threshold: number | null;
  direction: "increase" | "decrease" | null;
  method: string;
  triggers: number;
  trigger_rate: number;
  sample_size: number;
  effectiveness: number | null;
  current_value: number | null;
  current_triggered: boolean;
  improving: boolean | null;
  last_triggered: string | null;
  trigger_history: { month: string; value: number; triggered: boolean }[];
  rationale: string;
  months_evaluated: number;
}

interface BprRule {
  id: number;
  rule_name: string;
  rule_description: string;
  condition_expression: string;
  action: string;
  status: "active" | "needs_review" | "obsolete";
  effectiveness_score: number | null;
  category: string;
  last_triggered: string | null;
  evaluation: RuleEvaluation;
}

interface DriftData {
  has_data: boolean;
  kpis: KpiTarget[];
  drift_analysis: DriftKpi[];
  feature_drift: FeatureDrift[];
  bpr_rules: BprRule[];
  summary: {
    kpis_monitored: number;
    shifted: number;
    watching: number;
    stable: number;
    features_tracked: number;
    features_shifted: number;
    rules_total: number;
    rules_active: number;
    rules_needing_review: number;
    rules_obsolete: number;
    rules_measurable: number;
    average_effectiveness: number | null;
    rules_triggering_now: number;
    period_from: string | null;
    period_to: string | null;
  } | null;
}

const STATUS_TAG: Record<Status, string> = {
  shifted: "tag-danger",
  watch: "tag-warning",
  stable: "tag-success",
};

const STATUS_LABEL: Record<Status, string> = {
  shifted: "Shifted",
  watch: "Watch",
  stable: "Stable",
};

const FEATURE_STATUS_TAG: Record<FeatureDrift["status"], string> = {
  stable: "tag-success",
  moderate: "tag-warning",
  significant: "tag-danger",
};

const RULE_STATUS: Record<BprRule["status"], { label: string; tag: string }> = {
  active: { label: "Active", tag: "tag-success" },
  needs_review: { label: "Needs review", tag: "tag-warning" },
  obsolete: { label: "Obsolete", tag: "tag-danger" },
};

function signedPercent(value: number, digits = 1): string {
  if (Math.abs(value) < 0.05) return `${(0).toFixed(digits)}%`;
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function signedPoints(value: number): string {
  if (Math.abs(value) < 0.5) return "0pp";
  return `${value > 0 ? "+" : ""}${Math.round(value)}pp`;
}

function formatMetricValue(value: number | null, unit: string | null): string {
  if (value === null || value === undefined) return "—";
  if (unit === "USD") return formatCurrency(value);
  if (unit === "%") return formatPercent(value);
  if (unit === "×") return `${value.toFixed(2)}×`;
  return formatNumber(value);
}

function Sparkline({ points, markers }: { points: number[]; markers: number[] }) {
  if (!points || points.length < 2) return null;
  const width = 148;
  const height = 38;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const coords = points.map((value, index) => {
    const x = (index / (points.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 5) - 2.5;
    return [x, y] as const;
  });
  const markerSet = new Set(markers);

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" style={{ display: "block" }}>
      <polyline
        points={coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")}
        fill="none"
        stroke="#111111"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {coords.map(([x, y], index) => (
        markerSet.has(index) ? <circle key={index} cx={x} cy={y} r="3" fill="#dc2626" stroke="#ffffff" strokeWidth="1.2" /> : null
      ))}
      <circle cx={coords[coords.length - 1][0]} cy={coords[coords.length - 1][1]} r="2.2" fill="#111111" />
    </svg>
  );
}

function RuleCard({ rule, onUpdate }: { rule: BprRule; onUpdate: (id: number, body: { status?: string }) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState(rule.status);
  const [saving, setSaving] = useState(false);
  const cfg = RULE_STATUS[rule.status] ?? RULE_STATUS.active;
  const evaluation = rule.evaluation;

  const save = async () => {
    setSaving(true);
    try {
      await onUpdate(rule.id, { status });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const effectiveness = rule.effectiveness_score;
  const effectivenessLabel = effectiveness === null ? "Not measurable" : formatPercent(effectiveness * 100, 0);
  const threshold = evaluation?.threshold;
  const current = evaluation?.current_value;
  const ratio = threshold && current !== null && current !== undefined ? Math.min((current / threshold) * 100, 150) : 0;
  const triggerHistory = evaluation?.trigger_history ?? [];

  return (
    <div className="rule-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap", marginBottom: 3 }}>
            <span style={{ fontWeight: 800, fontSize: 13.5 }}>{rule.rule_name}</span>
            <span className={`tag ${cfg.tag}`}>{cfg.label}</span>
            {evaluation?.current_triggered && <span className="tag tag-danger">Triggers now</span>}
          </div>
          <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>{rule.rule_description}</p>
        </div>
        <button className="btn-ghost" onClick={() => setEditing(!editing)} style={{ padding: "4px 8px", fontSize: 11 }}>
          <Edit3 size={12} />
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
        {[
          ["Effectiveness", effectivenessLabel],
          ["Trigger rate", `${(evaluation?.trigger_rate ?? 0).toFixed(0)}%`],
          ["Last triggered", evaluation?.last_triggered ?? "Never"],
        ].map(([label, value]) => (
          <div key={label} style={{
            background: "#f9fafb", border: "1px solid var(--border)",
            borderRadius: 8, padding: "7px 9px",
          }}>
            <div style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 2 }}>
              {label}
            </div>
            <div style={{ fontSize: 12, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{value}</div>
          </div>
        ))}
      </div>

      {evaluation?.metric && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, marginBottom: 4 }}>
            <span style={{ color: "var(--text-muted)" }}>{evaluation.label}</span>
            <span style={{ fontWeight: 700 }}>
              {formatMetricValue(current, evaluation.unit)} vs {formatMetricValue(threshold, evaluation.unit)}
            </span>
          </div>
          <div className="progress-track" style={{ height: 4 }}>
            <div
              className="progress-fill"
              style={{ width: `${Math.min(ratio, 100)}%`, background: evaluation.current_triggered ? "#dc2626" : "#111111" }}
            />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9.5, color: "var(--text-muted)", marginTop: 3 }}>
            <span>{evaluation.triggers ?? 0} of {evaluation.months_evaluated ?? 0} months triggered</span>
            <span>
              {evaluation.improving === null || evaluation.improving === undefined ? "" : evaluation.improving ? "Improving" : "Deteriorating"}
            </span>
          </div>
        </div>
      )}

      {triggerHistory.length > 0 && (
        <div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 1.5, height: 24 }}>
            {triggerHistory.map((point) => {
              const values = triggerHistory.map((item) => item.value);
              const min = Math.min(...values);
              const max = Math.max(...values);
              const height = max > min ? 8 + ((point.value - min) / (max - min)) * 16 : 14;
              return (
                <div
                  key={point.month}
                  title={`${point.month}: ${formatMetricValue(point.value, evaluation?.unit ?? null)}${point.triggered ? " · triggered" : ""}`}
                  style={{
                    flex: 1, minWidth: 2, height, borderRadius: 1,
                    background: point.triggered ? "#dc2626" : "#d1d5db",
                  }}
                />
              );
            })}
          </div>
          <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: 2 }}>
            Trigger history · {evaluation?.method ?? "rule"} · n={evaluation?.sample_size ?? 0}
          </div>
        </div>
      )}

      <div className="rule-code" style={{ background: "#f9fafb" }}>
        <span style={{ fontWeight: 800 }}>IF </span>
        <span style={{ color: "var(--text-secondary)" }}>{rule.condition_expression}</span>
      </div>
      <div className="rule-code" style={{ background: "#f3f4f6" }}>
        <span style={{ fontWeight: 800 }}>THEN </span>
        <span style={{ color: "var(--text-secondary)" }}>{rule.action}</span>
      </div>

      {editing && (
        <div style={{ padding: 11, borderRadius: 9, background: "#f9fafb", border: "1px solid var(--border)" }}>
          <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: "0.07em", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 7 }}>
            Update status
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 9 }}>
            {(["active", "needs_review", "obsolete"] as const).map((option) => (
              <button
                key={option}
                onClick={() => setStatus(option)}
                className={option === status ? "btn-primary" : "btn-ghost"}
                style={{ padding: "4px 9px", fontSize: 11 }}
              >
                {RULE_STATUS[option].label}
              </button>
            ))}
          </div>
          <button className="btn-primary" onClick={save} disabled={saving} style={{ fontSize: 11.5 }}>
            <Save size={12} /> {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      )}
    </div>
  );
}

export default function DriftPage() {
  const [data, setData] = useState<DriftData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [referenceId, setReferenceId] = useState<number | undefined>();

  useEffect(() => {
    let cancelled = false;
    getDrift(referenceId)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError("");
      })
      .catch(() => {
        if (!cancelled) setError("Could not load drift analytics. Make sure the FastAPI server is running on port 8000.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [reloadKey, referenceId]);

  const refresh = () => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  };

  const adaptive = data && (data as { mode?: string }).mode === "adaptive"
    ? (data as unknown as AdaptiveModulePayload)
    : null;

  const handleRuleUpdate = async (id: number, body: { status?: string }) => {
    await patchRule(id, body);
    setReloadKey((key) => key + 1);
  };

  const header = (
    <div className="page-header" style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="page-title">
            <div className="page-title-icon"><BarChart3 size={18} /></div>
            Data Drift &amp; BPR
          </div>
          <p className="page-subtitle">
            {adaptive
              ? "Distribution shift between comparable datasets or periods, measured with PSI and distribution tests."
              : "ADWIN change points, PSI feature-mix shift, and business rules scored against their own trigger history."}
          </p>
        </div>
        <button className="btn-ghost" onClick={refresh} style={{ fontSize: 12 }}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>
    </div>
  );

  if (loading && !data) {
    return (
      <div>
        {header}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 14, marginBottom: 14 }}>
          {[...Array(4)].map((_, i) => <div key={i} className="skeleton" style={{ height: 120 }} />)}
        </div>
        <div className="skeleton" style={{ height: 280, marginBottom: 14 }} />
        <div className="skeleton" style={{ height: 300 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "64px 24px" }}>
          <AlertTriangle size={30} color="#b91c1c" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>Drift analytics unavailable</div>
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
        <AdaptiveModule
          payload={adaptive}
          onRefresh={refresh}
          onSelectReference={(dataset) => {
            setLoading(true);
            setReferenceId(dataset.id);
          }}
        />
      </div>
    );
  }

  if (!data?.has_data || !data.summary) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "72px 24px" }}>
          <BarChart3 size={28} color="#111111" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 6 }}>No KPI history yet</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 430, margin: "0 auto" }}>
            Drift monitoring needs several months of orders. Upload a dataset to start tracking.
          </p>
        </div>
      </div>
    );
  }

  const { summary, drift_analysis, feature_drift, bpr_rules, kpis } = data;
  const kpiByName = new Map(kpis.map((kpi) => [kpi.kpi_name, kpi]));

  return (
    <div>
      {header}

      {/* Summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(205px, 1fr))", gap: 14, marginBottom: 14 }}>
        {[
          {
            label: "KPIs monitored", value: `${summary.kpis_monitored}`,
            sub: `${summary.shifted} shifted · ${summary.watching} watch · ${summary.stable} stable`, icon: Activity,
          },
          {
            label: "Feature mix", value: `${summary.features_shifted}/${summary.features_tracked}`,
            sub: "PSI windows with significant shift", icon: TrendingUp,
          },
          {
            label: "Rules measurable", value: `${summary.rules_measurable}/${summary.rules_total}`,
            sub: summary.average_effectiveness !== null
              ? `${formatPercent(summary.average_effectiveness * 100, 0)} average effectiveness`
              : "No measurable rules yet",
            icon: Layers,
          },
          {
            label: "Triggering now", value: `${summary.rules_triggering_now}`,
            sub: `${summary.rules_active} active · ${summary.rules_needing_review} need review`, icon: Cpu,
          },
        ].map((item, index) => {
          const Icon = item.icon;
          return (
            <div key={item.label} className="kpi-card animate-fade-up" style={{ animationDelay: `${index * 55}ms`, opacity: 0 }}>
              <div className="kpi-accent-bar" />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 9 }}>
                <span className="kpi-label" style={{ marginBottom: 0 }}>{item.label}</span>
                <div className="kpi-icon-box" style={{ width: 30, height: 30 }}><Icon size={14} color="#000000" /></div>
              </div>
              <div className="kpi-value" style={{ fontSize: 26, marginBottom: 5 }}>{item.value}</div>
              <div className="kpi-sub">{item.sub}</div>
            </div>
          );
        })}
      </div>

      {/* KPI drift monitor */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div className="panel-header">
          <div>
            <div className="panel-title">KPI drift monitor</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              ADWIN change points + six-month level shift + volatility change
            </div>
          </div>
          <span className="tag" style={{ background: "#f3f4f6", borderColor: "var(--border)", color: "#111111" }}>
            <Cpu size={11} style={{ marginRight: 4 }} /> ADWIN
          </span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(255px, 1fr))", gap: 12 }}>
          {drift_analysis.map((kpi) => {
            const isCurrency = kpi.unit === "USD";
            const isPercent = kpi.unit === "%";
            const current = isCurrency ? formatCurrency(kpi.current) : isPercent ? formatPercent(kpi.current) : formatNumber(kpi.current);
            const target = kpiByName.get(kpi.kpi);
            return (
              <div key={kpi.kpi} style={{
                border: "1px solid var(--border)", borderRadius: 12, padding: 13, background: "#ffffff",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, marginBottom: 6 }}>
                  <div>
                    <div style={{ fontSize: 12.5, fontWeight: 800 }}>{kpi.kpi}</div>
                    <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>
                      latest {current} · mean {isCurrency ? formatCurrency(kpi.mean) : isPercent ? formatPercent(kpi.mean) : formatNumber(kpi.mean)}
                    </div>
                  </div>
                  <span className={`tag ${STATUS_TAG[kpi.status]}`}>{STATUS_LABEL[kpi.status]}</span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 8 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 10.5 }}>
                    <span style={{ color: "var(--text-secondary)" }}>
                      Level shift{" "}
                      <strong style={{ color: (kpi.level_pct ?? 0) < 0 ? "#b91c1c" : "#047857" }}>
                        {signedPercent(kpi.level_pct ?? 0)}
                      </strong>
                    </span>
                    <span style={{ color: "var(--text-secondary)" }}>
                      Volatility {isPercent ? `${kpi.volatility_pct.toFixed(1)}%` : formatPercent(kpi.volatility_pct)}
                      <span style={{ color: "var(--text-muted)" }}> ({signedPoints(kpi.volatility_change_pp)})</span>
                    </span>
                    <span style={{ color: "var(--text-secondary)" }}>
                      Trend {kpi.trend_pct > 0 ? "+" : ""}{kpi.trend_pct.toFixed(0)}% over period
                    </span>
                  </div>
                  <Sparkline points={kpi.series} markers={kpi.drift_points.map((point) => point.index)} />
                </div>

                <div style={{ marginTop: 8, fontSize: 10, color: "var(--text-muted)", borderTop: "1px solid var(--border-subtle)", paddingTop: 7 }}>
                  {kpi.n_drift_events > 0
                    ? `${kpi.n_drift_events} ADWIN change point${kpi.n_drift_events === 1 ? "" : "s"} detected`
                    : "No abrupt change point — movement is gradual"}
                  {target ? ` · target ${isCurrency ? formatCurrency(target.target_value) : isPercent ? formatPercent(target.target_value) : formatNumber(target.target_value)}` : ""}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* KPI targets */}
      <div className="panel animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div className="panel-body" style={{ paddingBottom: 0 }}>
          <div className="panel-header">
            <span className="panel-title">KPI scorecard</span>
            <span className="tag tag-info">Trailing 90 days</span>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>KPI</th>
                <th style={{ textAlign: "right" }}>Current</th>
                <th style={{ textAlign: "right" }}>Previous</th>
                <th style={{ textAlign: "right" }}>Target</th>
                <th style={{ textAlign: "right" }}>Gap to target</th>
                <th style={{ textAlign: "right" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {kpis.map((kpi) => {
                const isCurrency = kpi.unit === "USD";
                const isPercent = kpi.unit === "%";
                const fmt = (value: number) => isCurrency ? formatCurrency(value) : isPercent ? formatPercent(value) : formatNumber(value);
                return (
                  <tr key={kpi.kpi_name}>
                    <td className="td-primary">{kpi.kpi_name}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{fmt(kpi.current_value)}</td>
                    <td className="td-num" style={{ textAlign: "right", color: "var(--text-muted)" }}>{fmt(kpi.baseline_value)}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{fmt(kpi.target_value)}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>
                      {kpi.gap_pct === null ? "—" : `${kpi.gap_pct > 0 ? "+" : ""}${kpi.gap_pct.toFixed(1)}%`}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className={`tag ${kpi.on_target ? "tag-success" : "tag-warning"}`}>
                        {kpi.on_target ? "On target" : "Below target"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{ padding: "9px 16px", fontSize: 10.5, color: "var(--text-muted)", borderTop: "1px solid var(--border-subtle)" }}>
          Targets are set 10% ahead of the previous period, except churn which targets a 15% reduction.
        </div>
      </div>

      {/* Feature drift */}
      <div className="panel animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div className="panel-body" style={{ paddingBottom: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Feature &amp; mix drift</span>
            <span className="tag tag-info">PSI · first window vs latest</span>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 14, padding: "0 20px 18px" }}>
          {feature_drift.map((feature) => (
            <div key={feature.feature} style={{ border: "1px solid var(--border)", borderRadius: 11, padding: 13 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 5 }}>
                <span style={{ fontSize: 12.5, fontWeight: 800 }}>{feature.feature}</span>
                <span className={`tag ${FEATURE_STATUS_TAG[feature.status]}`}>
                  {feature.status === "significant" ? "Shifted" : feature.status === "moderate" ? "Moderate" : "Stable"}
                  {" · "}PSI {feature.psi.toFixed(3)}
                </span>
              </div>
              <p style={{ fontSize: 10.5, color: "var(--text-secondary)", lineHeight: 1.5, marginBottom: 9 }}>
                {feature.summary}
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                {feature.distribution.slice(0, 3).map((band) => (
                  <div key={band.band}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9.5, color: "var(--text-muted)", marginBottom: 2 }}>
                      <span>{band.band}</span>
                      <span>{band.baseline.toFixed(1)}% → {band.recent.toFixed(1)}%</span>
                    </div>
                    <div style={{ display: "flex", gap: 3 }}>
                      <div className="progress-track" style={{ height: 3, flex: 1 }}>
                        <div className="progress-fill" style={{ width: `${Math.min(band.baseline * 1.6, 100)}%`, background: "#9ca3af" }} />
                      </div>
                      <div className="progress-track" style={{ height: 3, flex: 1 }}>
                        <div className="progress-fill" style={{ width: `${Math.min(band.recent * 1.6, 100)}%`, background: "#111111" }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: 8 }}>
                {feature.method} · {feature.baseline_window} vs {feature.recent_window}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* BPR rules */}
      <div style={{ marginBottom: 13 }}>
        <div style={{ fontSize: 14, fontWeight: 800, marginBottom: 4 }}>Business process rules</div>
        <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          Effectiveness is measured from post-trigger movement in each rule&apos;s own metric — not a seeded constant.
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 12 }}>
        {bpr_rules.map((rule, index) => (
          <div key={rule.id} className="animate-fade-up" style={{ opacity: 0, animationDelay: `${index * 50}ms` }}>
            <RuleCard rule={rule} onUpdate={handleRuleUpdate} />
          </div>
        ))}
      </div>

      <div className="panel" style={{ marginTop: 14, padding: "11px 16px", fontSize: 10.5, color: "var(--text-muted)" }}>
        <CheckCircle2 size={12} style={{ display: "inline", marginRight: 5, verticalAlign: "-2px" }} />
        Window {summary.period_from} → {summary.period_to}. PSI thresholds: &lt;0.10 stable, &lt;0.25 moderate, ≥0.25 significant.
        Rule effectiveness uses the two months after each trigger; n is shown per rule.
      </div>
    </div>
  );
}
