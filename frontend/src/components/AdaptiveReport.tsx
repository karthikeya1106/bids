"use client";
import type { ReactNode } from "react";
import {
  Activity, AlertTriangle, BarChart3, CheckCircle2, FileBarChart2,
  Info, Layers, RefreshCw, Target, Users, Upload,
} from "lucide-react";
import {
  Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import ReportExportButtons from "./ReportExportButtons";
import TargetPicker, { type TargetInfo, type TargetSuggestion } from "./TargetPicker";

interface NumericRow {
  column: string; count: number; mean: number | null; median: number | null;
  std: number | null; min: number | null; max: number | null; missing_pct: number;
}
interface CategoryRow {
  column: string; unique: number; missing_pct: number;
  top: { value: string; count: number; share: number }[];
}
interface TimeRow {
  column: string; from?: string; to?: string; frequency?: string;
  periods?: number; coverage?: number; missing_pct?: number;
}
interface QualityRow {
  id: string; level: "error" | "warning" | "info"; column?: string | null;
  message: string; rows?: number;
}
interface ColumnRow {
  name: string; dtype: string; missing_pct: number; unique: number;
  mean?: number | null; min?: number | null; max?: number | null;
}
interface ClassMetrics {
  accuracy?: number | null; balanced_accuracy?: number | null;
  precision_weighted?: number | null; recall_weighted?: number | null;
  f1_weighted?: number | null; f1_macro?: number | null; roc_auc?: number | null;
}
interface TaskResult {
  type: string; available?: boolean; target?: string; method?: string;
  metrics?: ClassMetrics & { mae?: number | null; rmse?: number | null; r2?: number | null; mape?: number | null; naive_mae?: number | null; holdout_periods?: number };
  baseline?: Record<string, number | string | null>;
  confusion?: { labels: string[]; matrix: number[][] };
  class_distribution?: { label: string; count: number; share: number }[];
  importances?: { feature: string; importance: number }[];
  comparison?: { model: string; cv_f1_macro?: number | null; cv_mae?: number | null }[];
  split?: { train_rows?: number; test_rows?: number; stratified?: boolean };
  selected_model?: string;
  silhouette?: number | null;
  k?: number;
  clusters?: { cluster: number; size: number; share: number; description: string; distinguishing: { feature: string; z: number }[] }[];
  history?: { period: string; value: number }[];
  forecast?: { period: string; value: number; lower: number; upper: number }[];
  notes?: string[];
}
export interface AdaptiveReportData {
  mode: string;
  dataset_type?: string;
  schema_label?: string;
  schema_description?: string;
  task?: string;
  target?: string | null;
  org: {
    org_name: string | null; dataset_name: string; uploaded_at: string | null;
    row_count: number; customer_count: number; date_from: string | null; date_to: string | null;
  };
  profile: {
    rows: number; columns: number; duplicate_rows: number; missing_pct: number;
    type_counts: Record<string, number>; quality: QualityRow[];
    time_coverage: TimeRow | null;
    correlations: { a: string; b: string; r: number; strength: string }[];
    column_profiles: ColumnRow[];
  };
  adaptive: {
    summary: Record<string, unknown>;
    eda: { numeric: NumericRow[]; categorical: CategoryRow[]; datetime: TimeRow[] };
    task: TaskResult | null;
    clusters: TaskResult | null;
    supported_tasks: Record<string, { available: boolean; reason?: string }>;
    limitations: string[];
    generated_at: string;
  };
  notes?: string[];
  capabilities?: {
    dataset?: { id: number };
    target?: TargetInfo | null;
    target_suggestions?: TargetSuggestion[];
    understanding?: { structure: string; domain: string; evidence: string[]; template_note: string } | null;
  } | null;
  target_suggestion?: TargetSuggestion | null;
  generated_at: string;
}

const TYPE_LABELS: Record<string, string> = {
  numeric: "Number", datetime: "Date", identifier: "Identifier",
  categorical: "Category", text: "Text", boolean: "Yes / No",
};

function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  if (Number.isInteger(value)) return value.toLocaleString();
  return value.toFixed(digits);
}

function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function Section({ icon, title, subtitle, children }: { icon: ReactNode; title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="panel panel-body animate-fade-up" style={{ marginBottom: 18, opacity: 0 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 16 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8, background: "#000000",
          color: "#ffffff", display: "flex", alignItems: "center",
          justifyContent: "center", flexShrink: 0,
        }}>{icon}</div>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, color: "var(--text-primary)", letterSpacing: -0.2 }}>{title}</div>
          {subtitle && <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2, lineHeight: 1.5 }}>{subtitle}</div>}
        </div>
      </div>
      {children}
    </div>
  );
}

function Tile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div style={{ background: "#ffffff", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px" }}>
      <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, color: "#000000", letterSpacing: -0.6 }}>{value}</div>
      {detail && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>{detail}</div>}
    </div>
  );
}

function MetricGrid({ metrics }: { metrics: { label: string; value: string; hint?: string }[] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
      {metrics.map((metric) => (
        <div key={metric.label} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "12px 14px", background: "#fafafa" }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{metric.label}</div>
          <div style={{ fontSize: 19, fontWeight: 800, color: "#000000", marginTop: 3 }}>{metric.value}</div>
          {metric.hint && <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 2 }}>{metric.hint}</div>}
        </div>
      ))}
    </div>
  );
}

function BarList({ rows, suffix }: { rows: { label: string; value: number }[]; suffix?: string }) {
  const max = Math.max(...rows.map((row) => row.value || 0), 0.0001);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {rows.map((row, index) => (
        <div key={`${row.label}-${index}`}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
            <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{row.label}</span>
            <span style={{ color: "var(--text-secondary)", fontVariantNumeric: "tabular-nums" }}>
              {fmtNumber(row.value, 3)}{suffix || ""}
            </span>
          </div>
          <div style={{ height: 6, background: "#f3f4f6", borderRadius: 3, overflow: "hidden" }}>
            <div style={{
              height: "100%", width: `${Math.max(2, (row.value / max) * 100)}%`,
              background: "#111111", borderRadius: 3,
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function QualityPanel({ rows }: { rows: QualityRow[] }) {
  if (!rows.length) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "#065f46" }}>
        <CheckCircle2 size={15} /> No data-quality problems were detected.
      </div>
    );
  }
  const tone: Record<string, { bg: string; border: string; color: string }> = {
    error: { bg: "#fef2f2", border: "#fecaca", color: "#b91c1c" },
    warning: { bg: "#fffbeb", border: "#fde68a", color: "#92400e" },
    info: { bg: "#f8fafc", border: "#e2e8f0", color: "#475569" },
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {rows.map((finding) => {
        const colors = tone[finding.level] || tone.info;
        return (
          <div key={finding.id} style={{
            display: "flex", alignItems: "flex-start", gap: 9,
            background: colors.bg, border: `1px solid ${colors.border}`,
            borderRadius: 8, padding: "9px 12px",
          }}>
            {finding.level === "error" ? <AlertTriangle size={14} color={colors.color} style={{ marginTop: 2 }} />
              : finding.level === "warning" ? <AlertTriangle size={14} color={colors.color} style={{ marginTop: 2 }} />
              : <Info size={14} color={colors.color} style={{ marginTop: 2 }} />}
            <div style={{ fontSize: 12.5, color: colors.color, lineHeight: 1.5 }}>
              {finding.message}
              {finding.column && <span style={{ opacity: 0.7 }}> ({finding.column})</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConfusionMatrix({ labels, matrix }: { labels: string[]; matrix: number[][] }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="data-table" style={{ fontSize: 12 }}>
        <thead>
          <tr>
            <th>Actual ↓ / Predicted →</th>
            {labels.map((label) => <th key={label}>{label}</th>)}
          </tr>
        </thead>
        <tbody>
          {labels.map((label, rowIndex) => (
            <tr key={label}>
              <td style={{ fontWeight: 700 }}>{label}</td>
              {labels.map((inner, colIndex) => {
                const value = matrix[rowIndex]?.[colIndex] ?? 0;
                const total = Math.max(1, ...matrix.flat());
                return (
                  <td key={inner} style={{
                    background: rowIndex === colIndex
                      ? `rgba(17,17,17,${Math.min(0.85, value / total + 0.08)})`
                      : value ? "rgba(220,38,38,0.12)" : "transparent",
                    color: rowIndex === colIndex && value / total > 0.4 ? "#ffffff" : "inherit",
                    fontWeight: rowIndex === colIndex ? 700 : 400,
                    fontVariantNumeric: "tabular-nums",
                  }}>
                    {value}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TaskPanel({ task }: { task: TaskResult }) {
  if (!task.available) {
    return (
      <div style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.6 }}>
        {(task.notes || []).map((note) => <div key={note}>• {note}</div>)}
      </div>
    );
  }

  if (task.type === "classification") {
    const metrics = task.metrics || {};
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
          <strong style={{ color: "var(--text-primary)" }}>{task.selected_model}</strong> · {task.method}
          {task.split?.test_rows ? ` · held-out test rows: ${task.split.test_rows.toLocaleString()}` : ""}
        </div>
        <MetricGrid metrics={[
          { label: "Accuracy", value: pct(metrics.accuracy) },
          { label: "Balanced accuracy", value: pct(metrics.balanced_accuracy), hint: "fairer under imbalance" },
          { label: "F1 (weighted)", value: pct(metrics.f1_weighted) },
          { label: "F1 (macro)", value: pct(metrics.f1_macro) },
          { label: "ROC-AUC", value: metrics.roc_auc === null || metrics.roc_auc === undefined ? "n/a" : pct(metrics.roc_auc) },
          { label: "Most-frequent baseline", value: pct(task.baseline?.accuracy as number), hint: "accuracy to beat" },
        ]} />
        {task.class_distribution && task.class_distribution.length > 0 && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", marginBottom: 8 }}>Class distribution</div>
            <BarList rows={task.class_distribution.map((item) => ({ label: item.label, value: item.count }))} />
          </div>
        )}
        {task.confusion && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", marginBottom: 8 }}>Confusion matrix (holdout)</div>
            <ConfusionMatrix labels={task.confusion.labels} matrix={task.confusion.matrix} />
          </div>
        )}
        {task.importances && task.importances.length > 0 && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", marginBottom: 8 }}>Most influential features</div>
            <BarList
              rows={task.importances.map((item) => ({ label: item.feature, value: Math.round(item.importance * 1000) / 10 }))}
              suffix="%"
            />
          </div>
        )}
        <div style={{ fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.6 }}>
          {(task.notes || []).map((note) => <div key={note}>• {note}</div>)}
        </div>
      </div>
    );
  }

  if (task.type === "regression") {
    const metrics = task.metrics || {};
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
          <strong style={{ color: "var(--text-primary)" }}>{task.selected_model}</strong> · {task.method}
        </div>
        <MetricGrid metrics={[
          { label: "MAE", value: fmtNumber(metrics.mae) },
          { label: "RMSE", value: fmtNumber(metrics.rmse) },
          { label: "R²", value: fmtNumber(metrics.r2, 3) },
          { label: "MAPE", value: metrics.mape === null || metrics.mape === undefined ? "n/a" : `${fmtNumber(metrics.mape)}%` },
          { label: "Baseline MAE", value: fmtNumber(task.baseline?.mae as number), hint: "predict the mean" },
        ]} />
        {task.importances && task.importances.length > 0 && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", marginBottom: 8 }}>Most influential features</div>
            <BarList
              rows={task.importances.map((item) => ({ label: item.feature, value: Math.round(item.importance * 1000) / 10 }))}
              suffix="%"
            />
          </div>
        )}
        <div style={{ fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.6 }}>
          {(task.notes || []).map((note) => <div key={note}>• {note}</div>)}
        </div>
      </div>
    );
  }

  if (task.type === "clustering") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
          {task.method} · k = {task.k} · silhouette {fmtNumber(task.silhouette, 3)}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
          {(task.clusters || []).map((cluster) => (
            <div key={cluster.cluster} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "12px 14px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <span style={{ fontSize: 12.5, fontWeight: 800 }}>Segment {cluster.cluster + 1}</span>
                <span style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>{cluster.share}% · {cluster.size.toLocaleString()} rows</span>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 8 }}>{cluster.description}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {cluster.distinguishing.map((item) => (
                  <div key={item.feature} style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5 }}>
                    <span style={{ color: "var(--text-secondary)" }}>{item.feature}</span>
                    <span style={{ fontVariantNumeric: "tabular-nums", color: item.z >= 0 ? "#059669" : "#dc2626" }}>
                      {item.z >= 0 ? "+" : ""}{item.z}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.6 }}>
          {(task.notes || []).map((note) => <div key={note}>• {note}</div>)}
        </div>
      </div>
    );
  }

  if (task.type === "forecast") {
    const metrics = task.metrics || {};
    const chartData = [
      ...(task.history || []).map((row) => ({ period: row.period, history: row.value, forecast: null as number | null, lower: null as number | null, upper: null as number | null })),
      ...(task.forecast || []).map((row) => ({ period: row.period, history: null as number | null, forecast: row.value, lower: row.lower, upper: row.upper })),
    ];
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
          {task.method} · target <strong style={{ color: "var(--text-primary)" }}>{task.target}</strong>
        </div>
        <MetricGrid metrics={[
          { label: "Holdout MAE", value: fmtNumber(metrics.mae) },
          { label: "Holdout RMSE", value: fmtNumber(metrics.rmse) },
          { label: "MAPE", value: metrics.mape === null || metrics.mape === undefined ? "n/a" : `${fmtNumber(metrics.mape)}%` },
          { label: "Naïve MAE", value: fmtNumber(metrics.naive_mae), hint: "last-value baseline" },
          { label: "Holdout periods", value: String(metrics.holdout_periods ?? "—") },
        ]} />
        <div style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef0f2" />
              <XAxis dataKey="period" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 10 }} width={54} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="upper" stroke="none" fill="#d1d5db" fillOpacity={0.35} />
              <Area type="monotone" dataKey="lower" stroke="none" fill="#ffffff" fillOpacity={1} />
              <Line type="monotone" dataKey="history" stroke="#111111" strokeWidth={2} dot={false} connectNulls />
              <Line type="monotone" dataKey="forecast" stroke="#6b7280" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table" style={{ fontSize: 12 }}>
            <thead>
              <tr><th>Period</th><th>Forecast</th><th>Lower 95%</th><th>Upper 95%</th></tr>
            </thead>
            <tbody>
              {(task.forecast || []).map((row) => (
                <tr key={row.period}>
                  <td>{row.period}</td>
                  <td style={{ fontWeight: 700 }}>{fmtNumber(row.value)}</td>
                  <td>{fmtNumber(row.lower)}</td>
                  <td>{fmtNumber(row.upper)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.6 }}>
          {(task.notes || []).map((note) => <div key={note}>• {note}</div>)}
        </div>
      </div>
    );
  }

  return null;
}

export default function AdaptiveReport({ report, onRefresh }: { report: AdaptiveReportData; onRefresh: () => void }) {
  const { org, profile, adaptive } = report;
  const task = adaptive.task;
  const completeness = Math.max(0, 100 - (profile.missing_pct || 0));

  return (
    <div>
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div>
            <div className="page-title">
              <div className="page-title-icon"><FileBarChart2 size={18} /></div>
              Dataset Intelligence Report
            </div>
            <p className="page-subtitle">
              {report.schema_label || "Dataset"} · computed from the active file, with the analyses it actually supports.
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <ReportExportButtons />
            <button id="refresh-analysis" className="btn-ghost" onClick={onRefresh} style={{ fontSize: 12, gap: 6 }}>
              <RefreshCw size={13} /> Refresh
            </button>
          </div>
        </div>
      </div>

      <TargetPicker
        datasetId={report.capabilities?.dataset?.id}
        target={report.capabilities?.target}
        suggestions={report.capabilities?.target_suggestions}
        onChanged={onRefresh}
      />

      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 16, opacity: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <div style={{ width: 48, height: 48, borderRadius: 12, background: "#000000", color: "#ffffff", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <Layers size={22} />
          </div>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: 19, fontWeight: 800, color: "#000000", letterSpacing: -0.4 }}>
                {org.org_name || "Your Workspace"}
              </span>
              <span style={{ fontSize: 10.5, fontWeight: 700, padding: "3px 8px", borderRadius: 5, background: "#f3f4f6", border: "1px solid var(--border)" }}>
                {report.schema_label || report.dataset_type}
              </span>
              {report.task && (
                <span style={{ fontSize: 10.5, fontWeight: 700, padding: "3px 8px", borderRadius: 5, background: "#eef2ff", border: "1px solid #c7d2fe", color: "#3730a3" }}>
                  {report.task}{report.target ? ` · ${report.target}` : ""}
                </span>
              )}
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginTop: 3 }}>
              {org.dataset_name} · {org.row_count?.toLocaleString()} rows
              {org.customer_count ? ` · ${org.customer_count.toLocaleString()} customers` : ""}
              {org.date_from && org.date_to ? ` · ${org.date_from} → ${org.date_to}` : ""}
            </div>
          </div>
          <a href="/upload" className="btn-ghost" style={{ fontSize: 12, textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 6 }}>
            <Upload size={13} /> Upload another dataset
          </a>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginBottom: 18 }}>
        <Tile label="Rows" value={profile.rows.toLocaleString()} />
        <Tile label="Columns" value={String(profile.columns)} />
        <Tile label="Completeness" value={`${completeness.toFixed(1)}%`} detail={`${profile.missing_pct.toFixed(1)}% empty cells`} />
        <Tile label="Duplicates" value={profile.duplicate_rows.toLocaleString()} detail="identical rows" />
        <Tile label="Numeric" value={String(profile.type_counts?.numeric || 0)} detail="features" />
        <Tile label="Task" value={(task?.type || "eda").toUpperCase()} detail={report.target || "no supervised target"} />
      </div>

      <Section
        icon={<Target size={16} />}
        title="Analysis selection"
        subtitle="Only tasks that the data supports are offered. Reasons come from the actual column types and history."
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {Object.entries(adaptive.supported_tasks || {}).map(([name, info]) => (
            <div key={name} title={info.reason} style={{
              display: "flex", alignItems: "center", gap: 6, fontSize: 11.5,
              fontWeight: 600, padding: "6px 10px", borderRadius: 7,
              background: info.available ? "#ecfdf5" : "#f9fafb",
              border: `1px solid ${info.available ? "#a7f3d0" : "var(--border)"}`,
              color: info.available ? "#065f46" : "var(--text-muted)",
            }}>
              {info.available ? <CheckCircle2 size={12} /> : <Info size={12} />}
              {name.toUpperCase()}
              <span style={{ fontWeight: 400, opacity: 0.8 }}>— {info.reason}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section
        icon={<Target size={16} />}
        title={`${task?.type ? task.type[0].toUpperCase() + task.type.slice(1) : "Exploratory"} result`}
        subtitle={task?.type === "forecast"
          ? "Backtested on held-out periods; intervals widen with the horizon."
          : task?.type === "classification"
            ? "Metrics are measured on rows the model never saw."
            : task?.type === "regression"
              ? "Errors are measured on held-out rows."
              : "No supervised model was requested for this dataset."}
      >
        {task ? <TaskPanel task={task} /> : (
          <div style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.6 }}>
            This report uses profiling, distributions and clustering. To run a supervised model, upload the file again and choose a target column.
          </div>
        )}
      </Section>

      <Section
        icon={<AlertTriangle size={16} />}
        title="Data quality"
        subtitle="Findings from the profiling stage; errors here would have blocked ingestion."
      >
        <QualityPanel rows={profile.quality || []} />
      </Section>

      <Section
        icon={<BarChart3 size={16} />}
        title="Exploratory analysis"
        subtitle="Distributions, missingness and associations computed from the stored records."
      >
        {profile.time_coverage && (
          <div style={{ marginBottom: 14, fontSize: 12.5, color: "var(--text-secondary)" }}>
            <strong style={{ color: "var(--text-primary)" }}>Time coverage:</strong>{" "}
            {profile.time_coverage.column} · {profile.time_coverage.from} → {profile.time_coverage.to} ·{" "}
            {profile.time_coverage.frequency} · {profile.time_coverage.periods} periods
            {typeof profile.time_coverage.coverage === "number" ? ` · ${(profile.time_coverage.coverage * 100).toFixed(0)}% complete` : ""}
          </div>
        )}

        {adaptive.eda.numeric.length > 0 && (
          <div style={{ overflowX: "auto", marginBottom: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Numeric summary</div>
            <table className="data-table" style={{ fontSize: 12 }}>
              <thead><tr><th>Column</th><th>Mean</th><th>Median</th><th>Std</th><th>Min</th><th>Max</th><th>Missing</th></tr></thead>
              <tbody>
                {adaptive.eda.numeric.map((row) => (
                  <tr key={row.column}>
                    <td style={{ fontWeight: 600 }}>{row.column}</td>
                    <td>{fmtNumber(row.mean)}</td>
                    <td>{fmtNumber(row.median)}</td>
                    <td>{fmtNumber(row.std)}</td>
                    <td>{fmtNumber(row.min)}</td>
                    <td>{fmtNumber(row.max)}</td>
                    <td>{row.missing_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {adaptive.eda.categorical.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 }}>
            {adaptive.eda.categorical.slice(0, 6).map((column) => (
              <div key={column.column}>
                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 7 }}>{column.column}</div>
                <BarList rows={column.top.map((row) => ({ label: row.value, value: row.count }))} />
              </div>
            ))}
          </div>
        )}

        {profile.correlations.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Strongest associations (Pearson r)</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {profile.correlations.slice(0, 6).map((pair) => (
                <div key={`${pair.a}-${pair.b}`} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                  <span>{pair.a} ↔ {pair.b}</span>
                  <span style={{ fontWeight: 700, color: pair.r >= 0 ? "#065f46" : "#b91c1c", fontVariantNumeric: "tabular-nums" }}>
                    {pair.r.toFixed(3)} · {pair.strength}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      {adaptive.clusters && (
        <Section
          icon={<Layers size={16} />}
          title="Exploratory segments"
          subtitle="Unsupervised grouping of numeric features; descriptive, not predictive."
        >
          <TaskPanel task={adaptive.clusters} />
        </Section>
      )}

      <Section
        icon={<Activity size={16} />}
        title="Columns in this dataset"
        subtitle="Semantic type inferred from the values, not just the header."
      >
        <div style={{ overflowX: "auto" }}>
          <table className="data-table" style={{ fontSize: 12 }}>
            <thead><tr><th>Column</th><th>Type</th><th>Missing</th><th>Distinct</th></tr></thead>
            <tbody>
              {profile.column_profiles.map((column) => (
                <tr key={column.name}>
                  <td style={{ fontWeight: 600 }}>{column.name}</td>
                  <td>{TYPE_LABELS[column.dtype] || column.dtype}</td>
                  <td>{column.missing_pct}%</td>
                  <td>{column.unique.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section
        icon={<Info size={16} />}
        title="Limitations"
        subtitle="What this report does not claim."
      >
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.7 }}>
          {(adaptive.limitations || []).map((item) => <li key={item}>{item}</li>)}
          {(report.notes || []).map((item) => <li key={item}>{item}</li>)}
        </ul>
      </Section>

      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: "var(--text-muted)", marginBottom: 8 }}>
        <Users size={13} /> Generated {new Date(adaptive.generated_at || report.generated_at).toLocaleString()} from this workspace&apos;s active dataset only.
      </div>
    </div>
  );
}
