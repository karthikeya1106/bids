"use client";
import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import {
  AlertTriangle, BarChart3, CheckCircle2, Info, Layers, RefreshCw,
  Target as TargetIcon,
} from "lucide-react";
import TargetPicker, { type TargetInfo, type TargetSuggestion } from "./TargetPicker";

export interface AdaptiveColumn {
  key: string;
  label: string;
  format?: string;
  align?: string;
}

export interface AdaptiveSection {
  id: string;
  kind: "bar" | "table" | "histogram" | "line" | "confusion" | "notice" | "text";
  title: string;
  description?: string | null;
  note?: string | null;
  format?: string;
  horizontal?: boolean;
  data?: { label: string; value: number | null; secondary?: string | null }[];
  columns?: AdaptiveColumn[];
  rows?: Record<string, string | number | null>[];
  series?: string[];
  labels?: string[];
  matrix?: number[][];
  body?: string;
  tone?: string;
}

export interface AdaptiveModulePayload {
  has_data: boolean;
  compatible?: boolean;
  mode?: string;
  module: string;
  status: "ready" | "partial" | "unavailable";
  dataset?: { id: number; name: string; rows: number; columns: number; task?: string; target?: string | null } | null;
  schema_label?: string;
  target?: TargetInfo | null;
  summary?: { label: string; value: number | null; display: string; format: string; hint?: string | null }[];
  sections?: AdaptiveSection[];
  insights?: { title: string; detail: string; tone?: string }[];
  limitations?: string[];
  requires?: string[];
  method?: string;
  reference?: { label: string; mode: string; rows?: number } | null;
  reference_candidates?: { id: number; name: string; rows: number }[];
  understanding?: {
    structure: string;
    domain: string;
    evidence: string[];
    template_note: string;
  } | null;
  target_suggestions?: TargetSuggestion[];
}

const STATUS_STYLE: Record<string, { bg: string; border: string; color: string; label: string }> = {
  ready: { bg: "#ecfdf5", border: "#a7f3d0", color: "#065f46", label: "Ready" },
  partial: { bg: "#fffbeb", border: "#fcd34d", color: "#92400e", label: "Partially supported" },
  unavailable: { bg: "#fef2f2", border: "#fecaca", color: "#b91c1c", label: "Not supported" },
};

function formatValue(value: string | number | null | undefined, format?: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (format === "text") return String(value);
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (format === "percent") return `${number.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
  if (format === "currency") return `$${number.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (format === "decimal") return number.toLocaleString(undefined, { maximumFractionDigits: 3 });
  if (format === "rate") return `${(number * 100).toFixed(1)}%`;
  return number.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function SectionShell({ section, children }: { section: AdaptiveSection; children: React.ReactNode }) {
  return (
    <div className="panel panel-body animate-fade-up" style={{ marginBottom: 16, opacity: 0 }}>
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: "var(--text-primary)", letterSpacing: -0.2 }}>{section.title}</div>
        {section.description && (
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 3, lineHeight: 1.55 }}>{section.description}</div>
        )}
      </div>
      {children}
      {section.note && (
        <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 10, lineHeight: 1.5 }}>{section.note}</div>
      )}
    </div>
  );
}

function BarSection({ section }: { section: AdaptiveSection }) {
  const data = (section.data || []).map((row) => ({
    label: row.label.length > 28 ? `${row.label.slice(0, 27)}…` : row.label,
    value: row.value ?? 0,
    secondary: row.secondary || "",
  }));
  const height = Math.max(160, data.length * 32 + 40);
  return (
    <SectionShell section={section}>
      <div style={{ width: "100%", height }}>
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 18, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#ececec" />
            <XAxis type="number" tick={{ fontSize: 10.5 }} tickFormatter={(value) => formatValue(value, section.format)} />
            <YAxis type="category" dataKey="label" width={150} tick={{ fontSize: 11 }} />
            <Tooltip
              formatter={(value, _name, item) => {
                const numeric = Array.isArray(value) ? Number(value[0]) : Number(value);
                const secondary = (item as unknown as { payload?: { secondary?: string } })?.payload?.secondary;
                return [formatValue(numeric, section.format) + (secondary ? ` · ${secondary}` : ""), "Value"];
              }}
              contentStyle={{ fontSize: 11.5, borderRadius: 8, border: "1px solid #e5e7eb" }}
            />
            <Bar dataKey="value" fill="#111111" radius={[0, 4, 4, 0]} barSize={14} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </SectionShell>
  );
}

function HistogramSection({ section }: { section: AdaptiveSection }) {
  const palette = ["#111111", "#9ca3af", "#6b7280", "#d1d5db"];
  return (
    <SectionShell section={section}>
      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <BarChart data={section.data || []} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#ececec" />
            <XAxis dataKey="bin" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10.5 }} />
            <Tooltip contentStyle={{ fontSize: 11.5, borderRadius: 8, border: "1px solid #e5e7eb" }} />
            {(section.series || []).map((name, index) => (
              <Bar key={name} dataKey={name} fill={palette[index % palette.length]} radius={[3, 3, 0, 0]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div style={{ display: "flex", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
        {(section.series || []).map((name, index) => (
          <span key={name} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--text-secondary)" }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: palette[index % palette.length] }} />
            {name}
          </span>
        ))}
      </div>
    </SectionShell>
  );
}

function LineSection({ section }: { section: AdaptiveSection }) {
  return (
    <SectionShell section={section}>
      <div style={{ width: "100%", height: 260 }}>
        <ResponsiveContainer>
          <LineChart data={section.data || []} margin={{ top: 6, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#ececec" />
            <XAxis dataKey="period" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10.5 }} />
            <Tooltip contentStyle={{ fontSize: 11.5, borderRadius: 8, border: "1px solid #e5e7eb" }} />
            <Line type="monotone" dataKey="actual" stroke="#111111" strokeWidth={2} dot={false} connectNulls />
            <Line type="monotone" dataKey="forecast" stroke="#6b7280" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </SectionShell>
  );
}

function TableSection({ section }: { section: AdaptiveSection }) {
  const columns = section.columns || [];
  return (
    <SectionShell section={section}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  style={{
                    textAlign: column.align === "right" ? "right" : column.align === "center" ? "center" : "left",
                    padding: "7px 9px", borderBottom: "1px solid var(--border)",
                    fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.04em",
                    color: "var(--text-muted)", whiteSpace: "nowrap",
                  }}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(section.rows || []).map((row, index) => (
              <tr key={index} style={{ background: index % 2 ? "#fafafa" : "transparent" }}>
                {columns.map((column) => (
                  <td
                    key={column.key}
                    style={{
                      padding: "7px 9px", borderBottom: "1px solid #f1f1f1",
                      textAlign: column.align === "right" ? "right" : column.align === "center" ? "center" : "left",
                      whiteSpace: column.key === "profile" || column.key === "action" || column.key === "evidence" ? "normal" : "nowrap",
                      maxWidth: column.key === "action" || column.key === "evidence" ? 340 : undefined,
                    }}
                  >
                    {formatValue(row[column.key], column.format)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionShell>
  );
}

function ConfusionSection({ section }: { section: AdaptiveSection }) {
  const labels = section.labels || [];
  const matrix = section.matrix || [];
  return (
    <SectionShell section={section}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 11.5 }}>
          <thead>
            <tr>
              <th style={{ padding: 6 }} />
              {labels.map((label) => (
                <th key={label} style={{ padding: "6px 10px", fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase" }}>
                  Pred. {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, rowIndex) => (
              <tr key={rowIndex}>
                <th style={{ padding: "6px 10px", textAlign: "right", fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase" }}>
                  {labels[rowIndex]}
                </th>
                {row.map((value, columnIndex) => (
                  <td
                    key={columnIndex}
                    style={{
                      padding: "10px 14px", textAlign: "center", fontWeight: 700,
                      background: rowIndex === columnIndex ? "#111111" : "#ffffff",
                      color: rowIndex === columnIndex ? "#ffffff" : "#111111",
                      border: "1px solid #e5e7eb",
                    }}
                  >
                    {value.toLocaleString()}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionShell>
  );
}

function NoticeSection({ section }: { section: AdaptiveSection }) {
  const tone = section.tone || "info";
  const palette =
    tone === "warning"
      ? { bg: "#fffbeb", border: "#fcd34d", color: "#92400e", icon: <AlertTriangle size={14} /> }
      : tone === "danger"
        ? { bg: "#fef2f2", border: "#fecaca", color: "#b91c1c", icon: <AlertTriangle size={14} /> }
        : { bg: "#f8fafc", border: "#e2e8f0", color: "#334155", icon: <Info size={14} /> };
  return (
    <div className="panel panel-body" style={{ marginBottom: 14, background: palette.bg, borderColor: palette.border }}>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <span style={{ color: palette.color, marginTop: 1 }}>{palette.icon}</span>
        <div>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: palette.color }}>{section.title}</div>
          <div style={{ fontSize: 12, color: palette.color, opacity: 0.9, marginTop: 3, lineHeight: 1.55 }}>{section.body}</div>
        </div>
      </div>
    </div>
  );
}

function renderSection(section: AdaptiveSection) {
  if (section.kind === "bar") return <BarSection key={section.id} section={section} />;
  if (section.kind === "table") return <TableSection key={section.id} section={section} />;
  if (section.kind === "histogram") return <HistogramSection key={section.id} section={section} />;
  if (section.kind === "line") return <LineSection key={section.id} section={section} />;
  if (section.kind === "confusion") return <ConfusionSection key={section.id} section={section} />;
  return <NoticeSection key={section.id} section={section} />;
}

interface Props {
  payload: AdaptiveModulePayload;
  onRefresh: () => void;
  onSelectReference?: (dataset: { id: number; name: string }) => void;
}

export default function AdaptiveModule({ payload, onRefresh, onSelectReference }: Props) {
  const [referenceId, setReferenceId] = useState<string>("");
  const statusStyle = STATUS_STYLE[payload.status] || STATUS_STYLE.ready;
  const dataset = payload.dataset;

  const candidates = useMemo(() => payload.reference_candidates || [], [payload.reference_candidates]);
  const isDriftNeedingReference =
    payload.module === "drift" && candidates.length > 0 && !payload.reference;

  return (
    <div>
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 16, opacity: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{ width: 46, height: 46, borderRadius: 12, background: "#000000", color: "#ffffff", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <Layers size={20} />
          </div>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 16, fontWeight: 800, color: "#000000", letterSpacing: -0.3 }}>
                {payload.understanding?.domain || dataset?.name || "Active dataset"}
              </span>
              <span style={{ fontSize: 10.5, fontWeight: 700, padding: "3px 8px", borderRadius: 5, background: "#f3f4f6", border: "1px solid var(--border)" }}>
                {payload.schema_label}
              </span>
              <span style={{ fontSize: 10.5, fontWeight: 700, padding: "3px 8px", borderRadius: 5, background: statusStyle.bg, border: `1px solid ${statusStyle.border}`, color: statusStyle.color }}>
                {statusStyle.label}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 3 }}>
              {dataset?.name} · {(dataset?.rows ?? 0).toLocaleString()} rows · {dataset?.columns ?? 0} columns
              {payload.method ? ` · ${payload.method}` : ""}
            </div>
          </div>
          <button className="btn-ghost" onClick={onRefresh} style={{ fontSize: 12, gap: 6 }}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>

        {payload.understanding && (
          <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 6 }}>
              What this dataset is
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-primary)", marginBottom: 6 }}>{payload.understanding.structure}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {payload.understanding.evidence.map((item) => (
                <span key={item} style={{ fontSize: 11, padding: "4px 8px", borderRadius: 5, background: "#f9fafb", border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
                  {item}
                </span>
              ))}
            </div>
            <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 8, lineHeight: 1.5 }}>
              {payload.understanding.template_note}
            </div>
          </div>
        )}
      </div>

      <TargetPicker
        datasetId={dataset?.id}
        target={payload.target}
        suggestions={payload.target_suggestions}
        onChanged={onRefresh}
      />

      {isDriftNeedingReference && (
        <div className="panel panel-body" style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Choose a reference dataset</div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 10 }}>
            Drift compares this file against another committed dataset. Pick the baseline to compare against.
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <select className="input" value={referenceId} onChange={(event) => setReferenceId(event.target.value)} style={{ fontSize: 12, minWidth: 220, background: "#fff" }}>
              <option value="">Select a dataset…</option>
              {candidates.map((candidate) => (
                <option key={candidate.id} value={String(candidate.id)}>
                  {candidate.name} ({candidate.rows.toLocaleString()} rows)
                </option>
              ))}
            </select>
            <button
              className="btn-primary"
              disabled={!referenceId}
              style={{ fontSize: 12 }}
              onClick={() => {
                const selected = candidates.find((candidate) => String(candidate.id) === referenceId);
                if (selected) onSelectReference?.(selected);
              }}
            >
              Compare distributions
            </button>
          </div>
        </div>
      )}

      {payload.status !== "ready" && (payload.requires || []).length > 0 && (
        <div className="panel panel-body" style={{ marginBottom: 16, background: statusStyle.bg, borderColor: statusStyle.border }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: statusStyle.color, marginBottom: 6 }}>
            {payload.status === "unavailable" ? "This module cannot run on this dataset" : "What is needed for the rest"}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: statusStyle.color, lineHeight: 1.6 }}>
            {(payload.requires || []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {(payload.summary || []).length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(165px, 1fr))", gap: 12, marginBottom: 16 }}>
          {(payload.summary || []).map((item) => (
            <div key={item.label} className="panel panel-body" style={{ padding: "14px 16px" }}>
              <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
                {item.label}
              </div>
              <div style={{ fontSize: 21, fontWeight: 800, color: "#000000", letterSpacing: -0.5, marginTop: 4 }}>{item.display}</div>
              {item.hint && <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 3, lineHeight: 1.4 }}>{item.hint}</div>}
            </div>
          ))}
        </div>
      )}

      {(payload.insights || []).length > 0 && (
        <div className="panel panel-body" style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13.5, fontWeight: 800, marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
            <BarChart3 size={15} /> Findings
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
            {(payload.insights || []).map((insight) => (
              <div key={insight.title} style={{ border: "1px solid var(--border)", borderRadius: 9, padding: "11px 13px", background: "#fafafa" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 700 }}>
                  {insight.tone === "warning" ? <AlertTriangle size={13} color="#92400e" /> : <CheckCircle2 size={13} color="#065f46" />}
                  {insight.title}
                </div>
                <div style={{ fontSize: 11.5, color: "var(--text-secondary)", marginTop: 4, lineHeight: 1.55 }}>{insight.detail}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {(payload.sections || []).map(renderSection)}

      {(payload.limitations || []).length > 0 && (
        <div className="panel panel-body" style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 800, marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
            <TargetIcon size={14} /> Limitations
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.65 }}>
            {(payload.limitations || []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
