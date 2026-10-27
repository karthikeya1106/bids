"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Upload, FileSpreadsheet, CheckCircle2, AlertTriangle, AlertCircle,
  ArrowRight, RotateCcw, Database, ChevronRight, Loader, X,
  Sparkles, ShieldCheck, RefreshCw, Layers, Target, ListChecks,
  Eye, Info, Trash2, Play,
} from "lucide-react";
import {
  activateDataset, commitUpload, deleteDataset, getDatasets, getTemplates,
  getUploadStatus, previewUpload, reclassifyDataset,
  type ColumnProfile, type DatasetSummary, type MappingDecision,
  type ReclassifyResult, type UploadPreview, type UploadValidation,
} from "@/lib/api";

// ─── Constants ────────────────────────────────────────────────────────────────
const DTYPE_LABEL: Record<string, string> = {
  numeric: "Number", datetime: "Date", identifier: "Identifier",
  categorical: "Category", text: "Text", boolean: "Yes / No",
};

const STATUS_STYLE: Record<string, { label: string; bg: string; color: string; border: string }> = {
  auto: { label: "Auto-Mapped", bg: "#ecfdf5", color: "#065f46", border: "#a7f3d0" },
  manual: { label: "Manually Mapped", bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" },
  needs_review: { label: "Needs Review", bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
  derived: { label: "Derived", bg: "#eef2ff", color: "#4338ca", border: "#c7d2fe" },
  generated: { label: "Generated ID", bg: "#f3f4f6", color: "#374151", border: "#e5e7eb" },
  unmapped: { label: "Unmapped", bg: "#f9fafb", color: "#6b7280", border: "var(--border)" },
  unavailable: { label: "Unavailable", bg: "#f9fafb", color: "#6b7280", border: "var(--border)" },
  invalid: { label: "Invalid", bg: "#fef2f2", color: "#b91c1c", border: "#fecaca" },
};

const TASK_LABEL: Record<string, string> = {
  eda: "Profiling & exploratory analysis",
  clustering: "Clustering / segmentation",
  classification: "Classification",
  regression: "Regression",
  forecast: "Forecasting",
};

const PRIMARY_ID_FIELDS = new Set(["order_id", "subscriber_id", "transaction_id", "employee_id", "campaign_id"]);

type Step = "upload" | "review" | "loading" | "done";

interface CommitResult {
  success: boolean;
  rows_loaded: number;
  rows_skipped: number;
  rows_ignored: number;
  schema: string;
  schema_label: string;
  task: string;
  target: string | null;
  warnings: number;
  message: string;
  modules: Record<string, boolean>;
}

interface StatusPayload {
  has_data: boolean;
  dataset?: DatasetSummary | null;
  schema?: string;
  schema_label?: string;
  task?: string;
  target?: string | null;
  row_count?: number;
  customer_count?: number;
  total_sales?: number;
  modules?: Record<string, boolean>;
  notes?: string[];
}

interface LiveCheck {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail" | "info";
  detail: string;
  field?: string;
}

// ─── Client-side checks ───────────────────────────────────────────────────────
function columnByName(preview: UploadPreview, name: string | null): ColumnProfile | undefined {
  if (!name) return undefined;
  return preview.profile.column_profiles.find((column) => column.name === name);
}

// A target may be a schema field key ("sales") or a source column ("species").
function targetColumnFor(
  preview: UploadPreview,
  target: string | null,
  overrides: Record<string, string>,
): ColumnProfile | undefined {
  const direct = columnByName(preview, target);
  if (direct) return direct;
  if (target && preview.mapping[target]) {
    return columnByName(preview, effectiveValue(preview.mapping[target], overrides));
  }
  return undefined;
}

function typeVerdict(field: MappingDecision, column: ColumnProfile): { status: LiveCheck["status"]; detail: string } {
  if (field.dtype === "numeric") {
    if (column.dtype === "numeric" || column.dtype === "boolean") {
      return { status: "pass", detail: "numeric values" };
    }
    if (column.numeric_parse_pct >= 90) return { status: "warn", detail: "numeric values need parsing" };
    return { status: "fail", detail: "values are not numeric" };
  }
  if (field.dtype === "datetime") {
    if (column.dtype === "datetime") return { status: "pass", detail: "values parse as dates" };
    if (column.date_parse_pct >= 85) return { status: "warn", detail: "most values parse as dates" };
    return { status: "fail", detail: "values are not dates" };
  }
  if (field.dtype === "identifier") {
    if (column.unique_ratio >= 0.95) return { status: "pass", detail: "distinct identifier values" };
    // A customer or product key repeats once per transaction, which is normal.
    if (column.unique >= 5 && column.unique_ratio >= 0.02) {
      return { status: "pass", detail: `${column.unique} distinct keys, repeated across rows` };
    }
    return { status: "warn", detail: "too few distinct values for an identifier" };
  }
  if (field.dtype === "categorical") {
    if (["categorical", "boolean"].includes(column.dtype) || column.unique <= 50) {
      return { status: "pass", detail: `${column.unique} categories` };
    }
    return { status: "warn", detail: "high-cardinality column for a category" };
  }
  return { status: "pass", detail: "" };
}

function effectiveValue(decision: MappingDecision, overrides: Record<string, string>): string {
  if (Object.prototype.hasOwnProperty.call(overrides, decision.field)) return overrides[decision.field];
  return decision.value || "";
}

function fieldStatus(
  decision: MappingDecision,
  value: string,
  override: boolean,
  preview: UploadPreview,
): { key: string; checks: LiveCheck[] } {
  if (decision.status === "derived" && (!override || value === "__derived__")) {
    return { key: "derived", checks: [] };
  }
  if (!value) {
    return {
      key: "unmapped",
      checks: decision.required
        ? [{ id: `required:${decision.field}`, label: decision.label, status: "fail", detail: "required field is not mapped", field: decision.field }]
        : [],
    };
  }
  if (value === "__generate__") {
    return { key: "generated", checks: [] };
  }
  const column = columnByName(preview, value);
  if (!column) {
    return {
      key: "invalid",
      checks: [{ id: `missing:${decision.field}`, label: decision.label, status: "fail", detail: "column no longer exists in the file", field: decision.field }],
    };
  }
  const verdict = typeVerdict(decision, column);
  const checks: LiveCheck[] = [];
  if (verdict.status !== "pass") {
    checks.push({
      id: `type:${decision.field}`,
      label: `${decision.label} type`,
      status: decision.required && verdict.status === "fail" ? "fail" : verdict.status === "fail" ? "warn" : verdict.status,
      detail: verdict.detail,
      field: decision.field,
    });
  }
  if (column.missing_pct > 0) {
    const severe = column.missing_pct >= 30;
    checks.push({
      id: `missing:${decision.field}`,
      label: `${decision.label} completeness`,
      status: severe ? (decision.required ? "fail" : "warn") : "warn",
      detail: `${column.missing_pct.toFixed(1)}% of values are empty`,
      field: decision.field,
    });
  }
  if (decision.dtype === "identifier" && PRIMARY_ID_FIELDS.has(decision.field) && column.unique_ratio < 0.95) {
    checks.push({
      id: `id:${decision.field}`,
      label: `${decision.label} uniqueness`,
      status: "warn",
      detail: `only ${(column.unique_ratio * 100).toFixed(1)}% distinct values`,
      field: decision.field,
    });
  }
  let key = override ? "manual" : decision.status === "needs_review" ? "needs_review" : "auto";
  if (verdict.status === "fail") key = "invalid";
  return { key, checks };
}

function buildLiveChecks(
  preview: UploadPreview,
  overrides: Record<string, string>,
  task: string,
  target: string | null,
): LiveCheck[] {
  const checks: LiveCheck[] = [];
  const rows = preview.profile.rows;
  checks.push({
    id: "rows", label: "Data rows",
    status: rows === 0 ? "fail" : rows > 200000 ? "fail" : "pass",
    detail: `${rows.toLocaleString()} rows`,
  });
  if (preview.profile.duplicate_rows) {
    checks.push({
      id: "duplicate_rows", label: "Duplicate rows", status: "warn",
      detail: `${preview.profile.duplicate_rows.toLocaleString()} identical rows`,
    });
  }
  if (!preview.columns.length) {
    checks.push({ id: "columns", label: "Columns", status: "fail", detail: "the file has no columns" });
  }

  const used = new Map<string, string>();
  for (const decision of Object.values(preview.mapping)) {
    const value = effectiveValue(decision, overrides);
    const override = Object.prototype.hasOwnProperty.call(overrides, decision.field);
    const { checks: fieldChecks } = fieldStatus(decision, value, override, preview);
    checks.push(...fieldChecks);
    if (value && !value.startsWith("__")) {
      if (used.has(value)) {
        checks.push({
          id: `duplicate:${decision.field}`, label: `${decision.label} source`,
          status: "fail",
          detail: `'${value}' is already mapped to ${used.get(value)}; each source column can feed one field`,
          field: decision.field,
        });
      } else {
        used.set(value, decision.field);
      }
    }
  }

  if (task === "classification" || task === "regression") {
    checks.push({
      id: "task:target", label: "Analysis target",
      status: target ? "pass" : "fail",
      detail: target ? `target column selected` : "choose a target column",
    });
  }
  if (task === "clustering") {
    const numericMapped = Object.values(preview.mapping).filter((decision) => {
      const value = effectiveValue(decision, overrides);
      const column = columnByName(preview, value);
      return decision.dtype === "numeric" && column?.dtype === "numeric";
    }).length;
    checks.push({
      id: "task:clustering", label: "Clustering inputs",
      status: numericMapped >= 2 ? "pass" : "fail",
      detail: `${numericMapped} numeric feature(s) mapped; needs at least 2`,
    });
  }
  if (task === "forecast") {
    const timeField = Object.values(preview.mapping).find(
      (decision) => decision.dtype === "datetime" && effectiveValue(decision, overrides) &&
        !effectiveValue(decision, overrides).startsWith("__"),
    );
    const targetColumn = targetColumnFor(preview, target, overrides);
    const forecastInfo = preview.validation.forecast;
    const periods = forecastInfo?.periods || preview.profile.time_coverage?.periods || 0;
    checks.push({
      id: "task:forecast", label: "Forecast readiness",
      status: timeField && targetColumn && periods >= 3 ? "pass" : "fail",
      detail: timeField && targetColumn
        ? `${preview.profile.time_coverage?.frequency || "timeline"} · ${periods} periods`
        : "map a date field and choose a numeric measure",
    });
  }
  return checks;
}

function statusCounts(checks: LiveCheck[]) {
  return {
    errors: checks.filter((check) => check.status === "fail").length,
    warnings: checks.filter((check) => check.status === "warn").length,
  };
}

// ─── Small components ─────────────────────────────────────────────────────────
function StatusChip({ kind }: { kind: string }) {
  const style = STATUS_STYLE[kind] || STATUS_STYLE.unmapped;
  return (
    <span style={{
      fontSize: 10.5, fontWeight: 700, padding: "3px 8px", borderRadius: 6,
      background: style.bg, color: style.color, border: `1px solid ${style.border}`,
      whiteSpace: "nowrap", flexShrink: 0,
    }}>{style.label}</span>
  );
}

function StepDot({ index, label, current }: { index: number; label: string; current: number }) {
  const done = current > index;
  const active = current === index;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{
        width: 28, height: 28, borderRadius: "50%",
        border: `2px solid ${done || active ? "#000000" : "#d1d5db"}`,
        background: done ? "#000000" : active ? "#f3f4f6" : "transparent",
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0, transition: "all 0.3s ease",
      }}>
        {done ? <CheckCircle2 size={15} color="#ffffff" />
          : <span style={{ fontSize: 11, fontWeight: 800, color: active ? "#000000" : "#6b7280" }}>{index + 1}</span>}
      </div>
      <span style={{ fontSize: 12.5, fontWeight: active ? 700 : 500, color: active ? "#000000" : done ? "#374151" : "#9ca3af" }}>{label}</span>
    </div>
  );
}

function checkTone(status: LiveCheck["status"]) {
  if (status === "fail") return { bg: "#fef2f2", border: "#fecaca", color: "#b91c1c", icon: <AlertCircle size={13} /> };
  if (status === "warn") return { bg: "#fffbeb", border: "#fde68a", color: "#92400e", icon: <AlertTriangle size={13} /> };
  if (status === "pass") return { bg: "#ecfdf5", border: "#a7f3d0", color: "#065f46", icon: <CheckCircle2 size={13} /> };
  return { bg: "#f8fafc", border: "#e2e8f0", color: "#475569", icon: <Info size={13} /> };
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function UploadPage() {
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [orgName, setOrgName] = useState("");
  const [schemaChoice, setSchemaChoice] = useState("auto");
  const [templates, setTemplates] = useState<{ id: string; label: string; description: string }[]>([]);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [task, setTask] = useState("eda");
  const [target, setTarget] = useState<string | null>(null);
  const [showOptional, setShowOptional] = useState(false);
  const [loading, setLoading] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [error, setError] = useState("");
  const [serverChecks, setServerChecks] = useState<LiveCheck[]>([]);
  const [result, setResult] = useState<CommitResult | null>(null);
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [busyDataset, setBusyDataset] = useState<number | null>(null);
  const [reclassifying, setReclassifying] = useState<number | null>(null);
  const [reclassResult, setReclassResult] = useState<ReclassifyResult | null>(null);
  const [reclassError, setReclassError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadStatus = useCallback(() => {
    getUploadStatus().then(setStatus).catch(() => {});
  }, []);
  const loadDatasets = useCallback(() => {
    getDatasets().then((payload) => setDatasets(payload.datasets)).catch(() => {});
  }, []);

  useEffect(() => {
    loadStatus();
    loadDatasets();
    getTemplates().then((payload) => setTemplates(payload.templates)).catch(() => {});
  }, [loadStatus, loadDatasets]);

  const handleFile = (candidate: File) => {
    const extension = candidate.name.split(".").pop()?.toLowerCase();
    if (!["csv", "txt", "xlsx", "xls"].includes(extension || "")) {
      setError("Only CSV or Excel files (.csv, .xlsx, .xls) are supported.");
      return;
    }
    if (candidate.size > 40 * 1024 * 1024) {
      setError("This file is larger than 40 MB. Split it before uploading.");
      return;
    }
    setError("");
    setFile(candidate);
  };

  const runPreview = async (analysisType: string) => {
    if (!file) return;
    setLoading(true);
    setError("");
    setServerChecks([]);
    try {
      const payload = await previewUpload(file, { analysisType });
      setPreview(payload);
      setSchemaChoice(payload.analysis_type);
      setOverrides({});
      setTask(payload.task || "eda");
      setTarget(payload.target || null);
      setStep("review");
    } catch (requestError: unknown) {
      const detail = (requestError as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "Could not analyse this file.");
    } finally {
      setLoading(false);
    }
  };

  const handleSchemaChange = (value: string) => {
    setSchemaChoice(value);
    if (value === "auto") {
      runPreview("auto");
    } else {
      runPreview(value);
    }
    // Let the user pick after re-analysis so a stale mapping cannot be committed.
    setOverrides({});
  };

  const decisions = useMemo(
    () => (preview ? Object.values(preview.mapping) : []),
    [preview],
  );

  const checks = useMemo(
    () => (preview ? buildLiveChecks(preview, overrides, task, target) : []),
    [preview, overrides, task, target],
  );
  const counts = statusCounts(checks);
  const ready = counts.errors === 0 && Boolean(preview);

  const rows = useMemo(() => {
    if (!preview) return [] as { decision: MappingDecision; value: string; override: boolean; status: string }[];
    return decisions
      .map((decision) => {
        const value = effectiveValue(decision, overrides);
        const override = Object.prototype.hasOwnProperty.call(overrides, decision.field);
        const { key } = fieldStatus(decision, value, override, preview);
        return { decision, value, override, status: key };
      })
      .sort((a, b) => {
        if (a.decision.required !== b.decision.required) return a.decision.required ? -1 : 1;
        const rank = (kind: string) => (kind === "unmapped" ? 3 : kind === "invalid" ? 2 : 1);
        return rank(a.status) - rank(b.status);
      });
  }, [decisions, overrides, preview]);

  const visibleRows = showOptional ? rows : rows.filter((row) => row.decision.required || row.status !== "unmapped");
  const hiddenOptional = rows.length - visibleRows.length;

  const numericFields = useMemo(() => {
    if (!preview) return [];
    return Object.values(preview.mapping).filter(
      (decision) => decision.dtype === "numeric" && effectiveValue(decision, overrides) &&
        !effectiveValue(decision, overrides).startsWith("__"),
    );
  }, [preview, overrides]);

  const taskOptions = useMemo(() => {
    if (!preview) return [] as { key: string; label: string; reason: string; available: boolean }[];
    return Object.entries(preview.tasks).map(([key, info]) => ({
      key, label: TASK_LABEL[key] || key, reason: info.reason, available: info.available,
    }));
  }, [preview]);

  const targetOptions = useMemo(() => {
    if (!preview) return [] as { value: string; label: string; reason: string }[];
    const options: { value: string; label: string; reason: string }[] = [];
    if (task === "classification" || task === "regression") {
      for (const candidate of preview.targets.filter((item) => item.task === task)) {
        options.push({
          value: candidate.column,
          label: candidate.column,
          reason: candidate.reason,
        });
      }
      // Mapped schema fields that are marked as targets are offered by key too.
      for (const decision of Object.values(preview.mapping)) {
        if (decision.target && effectiveValue(decision, overrides) && !options.some((item) => item.value === decision.field)) {
          options.push({ value: decision.field, label: `${decision.label} (${decision.field})`, reason: decision.description });
        }
      }
    }
    if (task === "forecast") {
      for (const decision of numericFields) {
        options.push({
          value: decision.field,
          label: `${decision.label} (${decision.column})`,
          reason: "numeric measure aggregated by period",
        });
      }
    }
    return options;
  }, [preview, task, overrides, numericFields]);

  const handleTaskChange = (nextTask: string) => {
    setTask(nextTask);
    const info = preview?.tasks?.[nextTask];
    if (nextTask === "eda" || nextTask === "clustering") {
      setTarget(null);
      return;
    }
    const candidate = preview?.targets.find((item) => item.task === nextTask)?.column;
    setTarget(info?.target || candidate || null);
  };

  const handleCommit = async () => {
    if (!file || !preview) return;
    if (!ready) {
      setError("Fix the blocking validation issues before loading this dataset.");
      return;
    }
    setCommitting(true);
    setError("");
    setServerChecks([]);
    setStep("loading");
    try {
      const mapping: Record<string, string> = {};
      for (const decision of Object.values(preview.mapping)) {
        mapping[decision.field] = effectiveValue(decision, overrides);
      }
      const response = await commitUpload(file, {
        schema: preview.analysis_type,
        mapping,
        orgName: orgName.trim() || undefined,
        task,
        target: target || "",
      });
      setResult(response as CommitResult);
      setStep("done");
      loadStatus();
      loadDatasets();
    } catch (requestError: unknown) {
      const detail = (requestError as {
        response?: { data?: { detail?: string | { message?: string; validation?: UploadValidation } } };
      })?.response?.data?.detail;
      if (typeof detail === "object" && detail?.validation) {
        setServerChecks(detail.validation.checks as unknown as LiveCheck[]);
        setError(detail.message || "The server rejected this dataset.");
      } else {
        setError(typeof detail === "string" ? detail : "Upload failed.");
      }
      setStep("review");
    } finally {
      setCommitting(false);
    }
  };

  const reset = () => {
    setStep("upload");
    setFile(null);
    setPreview(null);
    setOverrides({});
    setResult(null);
    setError("");
    setServerChecks([]);
    setOrgName("");
    setSchemaChoice("auto");
    setTask("eda");
    setTarget(null);
  };

  const refreshDatasetState = async () => {
    loadDatasets();
    loadStatus();
  };

  const handleActivate = async (id: number) => {
    setBusyDataset(id);
    try {
      await activateDataset(id);
      await refreshDatasetState();
    } catch {
      setError("Could not activate that dataset.");
    } finally {
      setBusyDataset(null);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm("Delete this stored dataset? Its records are removed from your workspace.")) return;
    setBusyDataset(id);
    try {
      await deleteDataset(id);
      await refreshDatasetState();
    } catch {
      setError("Could not delete that dataset.");
    } finally {
      setBusyDataset(null);
    }
  };

  const handleReclassify = async (id: number) => {
    setReclassifying(id);
    setReclassResult(null);
    setReclassError("");
    try {
      const payload = await reclassifyDataset(id);
      setReclassResult(payload);
      await refreshDatasetState();
    } catch (requestError: unknown) {
      const detail = (requestError as {
        response?: { data?: { detail?: string | { message?: string } } };
      })?.response?.data?.detail;
      setReclassError(
        typeof detail === "string"
          ? detail
          : detail?.message || "Could not re-analyse that dataset.",
      );
    } finally {
      setReclassifying(null);
    }
  };

  const stepIndex = step === "upload" ? 0 : step === "review" ? 1 : step === "loading" ? 2 : 3;
  const mappedCount = rows.filter((row) => ["auto", "manual"].includes(row.status)).length;
  const derivedCount = rows.filter((row) => ["derived", "generated"].includes(row.status)).length;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <div className="page-title-icon"><Upload size={18} /></div>
          Data Upload & Dataset Setup
        </div>
        <p className="page-subtitle">
          Upload a CSV or Excel file. BIDS profiles the actual values, explains every column match,
          validates the data before writing, and runs only the analyses your data supports.
        </p>
      </div>

      {/* Current active dataset */}
      {status?.has_data && status.dataset && (
        <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, opacity: 0, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", borderLeft: "4px solid #000000" }}>
          <Database size={18} style={{ flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 12.5, fontWeight: 700 }}>Active dataset</div>
            <div style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
              {status.dataset.name} · {status.schema_label} · {(status.row_count || 0).toLocaleString()} rows
              {status.target ? ` · ${status.task} on ${status.target}` : ""}
            </div>
          </div>
          <span style={{ fontSize: 10.5, fontWeight: 800, background: "#f3f4f6", border: "1px solid var(--border)", borderRadius: 6, padding: "4px 10px" }}>LIVE</span>
        </div>
      )}

      {/* Step progress */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <StepDot index={0} label="Upload file" current={stepIndex} />
          <ChevronRight size={13} style={{ color: "#9ca3af" }} />
          <StepDot index={1} label="Review & map" current={stepIndex} />
          <ChevronRight size={13} style={{ color: "#9ca3af" }} />
          <StepDot index={2} label="Validate & load" current={stepIndex} />
          <ChevronRight size={13} style={{ color: "#9ca3af" }} />
          <StepDot index={3} label="Done" current={stepIndex} />
        </div>
      </div>

      {error && (
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "12px 14px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, marginBottom: 14, fontSize: 13, color: "#b91c1c", fontWeight: 500 }}>
          <AlertCircle size={16} style={{ marginTop: 1 }} />
          <div style={{ flex: 1 }}>{error}</div>
          <button onClick={() => setError("")} style={{ background: "none", border: "none", color: "#b91c1c", cursor: "pointer" }}><X size={14} /></button>
        </div>
      )}

      {/* ── Step 1: pick a file ─────────────────────────────────────────────── */}
      {step === "upload" && (
        <div className="animate-fade-up" style={{ opacity: 0 }}>
          <div className="panel panel-body" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--text-secondary)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Organization name <span style={{ textTransform: "none", fontWeight: 400, color: "var(--text-muted)" }}>(optional)</span>
            </div>
            <input
              value={orgName}
              onChange={(event) => setOrgName(event.target.value)}
              placeholder="e.g. Acme Corp"
              style={{
                width: "100%", background: "#ffffff", border: "1px solid var(--border)",
                borderRadius: 8, fontSize: 13, padding: "10px 14px", fontFamily: "inherit",
                outline: "none", boxSizing: "border-box",
              }}
            />
          </div>

          <div
            onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const dropped = event.dataTransfer.files[0];
              if (dropped) handleFile(dropped);
            }}
            onClick={() => fileRef.current?.click()}
            style={{
              border: `2px dashed ${dragging ? "#000000" : file ? "#4b5563" : "#d1d5db"}`,
              borderRadius: 16, padding: "48px 32px", textAlign: "center", cursor: "pointer",
              background: dragging ? "#f3f4f6" : "#ffffff", transition: "all 0.2s ease",
            }}
          >
            <input
              ref={fileRef} type="file" accept=".csv,.txt,.xlsx,.xls" style={{ display: "none" }}
              onChange={(event) => event.target.files?.[0] && handleFile(event.target.files[0])}
            />
            <div style={{ width: 56, height: 56, borderRadius: 14, background: "#000000", color: "#ffffff", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 18px" }}>
              {file ? <FileSpreadsheet size={24} /> : <Upload size={24} />}
            </div>
            {file ? (
              <>
                <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 4 }}>{file.name}</div>
                <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 18 }}>
                  {(file.size / 1024).toFixed(1)} KB · click to change
                </div>
                <button
                  className="btn-primary" disabled={loading}
                  onClick={(event) => { event.stopPropagation(); runPreview("auto"); }}
                  style={{ fontSize: 13, padding: "10px 26px" }}
                >
                  {loading ? <><Loader size={14} style={{ animation: "spin 1s linear infinite" }} /> Profiling…</>
                    : <><Sparkles size={14} /> Profile & analyse <ArrowRight size={14} /></>}
                </button>
              </>
            ) : (
              <>
                <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 6 }}>Drop a dataset here</div>
                <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>or click to browse</div>
                <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 8 }}>
                  CSV, XLSX or XLS · up to 40 MB / 200,000 rows
                </div>
              </>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginTop: 14 }}>
            {[
              { title: "Profiled before mapping", body: "Types are inferred from values, missingness and outliers are measured." },
              { title: "Explainable matches", body: "Every suggestion shows its confidence and the evidence behind it." },
              { title: "No fabricated data", body: "Required fields must exist. Only documented derivations are computed." },
            ].map((card) => (
              <div key={card.title} className="panel panel-body" style={{ padding: "12px 14px" }}>
                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4 }}>{card.title}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>{card.body}</div>
              </div>
            ))}
          </div>

          {datasets.length > 0 && (
            <div className="panel panel-body" style={{ marginTop: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <Layers size={15} />
                <span style={{ fontSize: 13, fontWeight: 800 }}>Your datasets</span>
                <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{datasets.length} stored · switching rebuilds the analytics</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {datasets.map((dataset) => (
                  <div key={dataset.id} style={{
                    display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
                    border: "1px solid var(--border)", borderRadius: 9, padding: "10px 12px",
                    background: dataset.is_active ? "#fafafa" : "#ffffff",
                  }}>
                    <div style={{ flex: 1, minWidth: 200 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 700 }}>
                        {dataset.name}
                        {dataset.is_active && <span style={{ marginLeft: 8, fontSize: 10, fontWeight: 800, background: "#111111", color: "#ffffff", borderRadius: 4, padding: "2px 6px" }}>ACTIVE</span>}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                        {dataset.schema_label} · {dataset.rows.toLocaleString()} rows · {dataset.task}
                        {dataset.uploaded_at ? ` · ${new Date(dataset.uploaded_at).toLocaleDateString()}` : ""}
                      </div>
                    </div>
                    {!dataset.is_active && (
                      <button className="btn-ghost" disabled={busyDataset === dataset.id} onClick={() => handleActivate(dataset.id)} style={{ fontSize: 11.5 }}>
                        {busyDataset === dataset.id ? <Loader size={12} style={{ animation: "spin 1s linear infinite" }} /> : <Play size={12} />} Activate
                      </button>
                    )}
                    <button
                      className="btn-ghost"
                      id={`reclassify-${dataset.id}`}
                      disabled={busyDataset === dataset.id || reclassifying !== null}
                      onClick={() => handleReclassify(dataset.id)}
                      title="Re-run profiling, classification and mapping on the stored rows"
                      style={{ fontSize: 11.5 }}
                    >
                      {reclassifying === dataset.id
                        ? <><Loader size={12} style={{ animation: "spin 1s linear infinite" }} /> Re-analysing…</>
                        : <><Sparkles size={12} /> Re-analyse</>}
                    </button>
                    <button className="btn-ghost" disabled={busyDataset === dataset.id || reclassifying !== null} onClick={() => handleDelete(dataset.id)} style={{ fontSize: 11.5, color: "#b91c1c" }}>
                      <Trash2 size={12} /> Delete
                    </button>
                  </div>
                ))}
              </div>

              {reclassifying !== null && (
                <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 7 }}>
                  <Loader size={12} style={{ animation: "spin 1s linear infinite" }} />
                  Re-running the classifier on the stored rows. Large datasets take a few seconds.
                </div>
              )}

              {reclassError && (
                <div style={{ marginTop: 12, border: "1px solid #fecaca", background: "#fef2f2", borderRadius: 9, padding: "10px 12px", fontSize: 12, color: "#b91c1c", lineHeight: 1.55 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 800, marginBottom: 3 }}>
                    <AlertCircle size={13} /> Not reclassified
                  </div>
                  {reclassError}
                  <div style={{ marginTop: 4, color: "#7f1d1d" }}>
                    The stored dataset was left exactly as it was.
                  </div>
                </div>
              )}

              {reclassResult && (
                <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
                    {reclassResult.status === "unchanged"
                      ? <CheckCircle2 size={15} color="#065f46" />
                      : <Sparkles size={15} />}
                    <span style={{ fontSize: 12.5, fontWeight: 800 }}>{reclassResult.message}</span>
                  </div>

                  {reclassResult.status !== "unchanged" && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 10, fontSize: 11.5 }}>
                      <span style={{
                        border: "1px solid var(--border)", borderRadius: 6, padding: "3px 8px",
                        background: "#f9fafb", color: "var(--text-secondary)",
                      }}>
                        was: {reclassResult.before.schema_label}
                      </span>
                      <ArrowRight size={13} color="var(--text-muted)" />
                      <span style={{
                        border: "1px solid #a7f3d0", borderRadius: 6, padding: "3px 8px",
                        background: "#ecfdf5", color: "#065f46", fontWeight: 700,
                      }}>
                        now: {reclassResult.after.schema_label}
                      </span>
                      <span style={{ color: "var(--text-muted)" }}>
                        {reclassResult.after.rows.toLocaleString()} rows ·{" "}
                        {reclassResult.after.confidence !== null && reclassResult.after.confidence !== undefined
                          ? `${reclassResult.after.confidence}% template confidence · `
                          : ""}
                        {reclassResult.rows_rewritten.toLocaleString()} records rewritten
                      </span>
                    </div>
                  )}

                  {reclassResult.mapping_changes.length > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 11, fontWeight: 800, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 5 }}>
                        Mapping changes ({reclassResult.mapping_changes.length})
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {reclassResult.mapping_changes.slice(0, 6).map((change) => (
                          <div key={change.field} style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
                            <strong style={{ color: "var(--text-primary)" }}>{change.label}</strong>:{" "}
                            {change.before || "unmapped"} → {change.after || "unmapped"}
                          </div>
                        ))}
                        {reclassResult.mapping_changes.length > 6 && (
                          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                            +{reclassResult.mapping_changes.length - 6} more
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {reclassResult.review.length > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 11, fontWeight: 800, color: "#92400e", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 5 }}>
                        Needs your review
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                        {reclassResult.review.map((item, index) => (
                          <div key={`${item.kind}-${index}`} style={{
                            display: "flex", alignItems: "flex-start", gap: 7, fontSize: 11.5,
                            background: item.kind === "low_confidence" || item.kind === "mapping_conflict" ? "#fffbeb" : "#f8fafc",
                            border: `1px solid ${item.kind === "low_confidence" || item.kind === "mapping_conflict" ? "#fde68a" : "var(--border)"}`,
                            borderRadius: 7, padding: "7px 9px", color: "var(--text-secondary)", lineHeight: 1.5,
                          }}>
                            <Info size={12} style={{ marginTop: 2, flexShrink: 0 }} />
                            <span>{item.message}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {reclassResult.notes.length > 0 && (
                    <div style={{ fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.6 }}>
                      {reclassResult.notes.map((note) => <div key={note}>• {note}</div>)}
                    </div>
                  )}

                  <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                    <a href="/analysis" className="btn-ghost" style={{ fontSize: 11.5, textDecoration: "none" }}>
                      Open Analysis Report <ArrowRight size={12} />
                    </a>
                    {reclassResult.dataset.is_active && (
                      <a href="/dashboard" className="btn-ghost" style={{ fontSize: 11.5, textDecoration: "none" }}>
                        Executive Dashboard <ArrowRight size={12} />
                      </a>
                    )}
                    <button className="btn-ghost" onClick={() => setReclassResult(null)} style={{ fontSize: 11.5 }}>
                      <X size={12} /> Dismiss
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Step 2: classification, mapping, validation ──────────────────────── */}
      {step === "review" && preview && (
        <div className="animate-fade-up" style={{ opacity: 0 }}>
          {/* Dataset header */}
          <div className="panel panel-body" style={{ marginBottom: 14, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <FileSpreadsheet size={18} />
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 13.5, fontWeight: 700 }}>{preview.filename}</div>
              <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                {preview.total_rows.toLocaleString()} rows · {preview.columns.length} columns ·{" "}
                {(100 - preview.profile.missing_pct).toFixed(1)}% complete
              </div>
            </div>
            <button className="btn-ghost" onClick={reset} style={{ fontSize: 11.5 }}>
              <RotateCcw size={12} /> Change file
            </button>
          </div>

          {/* Classification */}
          <div className="panel" style={{ marginBottom: 14, padding: "20px 22px", background: "linear-gradient(135deg, #09090b 0%, #18181b 100%)", color: "#ffffff", borderRadius: 14, border: "1px solid #27272a" }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start", minWidth: 260, flex: 1 }}>
                <div style={{ width: 38, height: 38, borderRadius: 10, background: "linear-gradient(135deg, #2563eb 0%, #7c3aed 100%)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  <Sparkles size={19} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 15, fontWeight: 800 }}>{preview.classification.label}</span>
                    <span style={{
                      fontSize: 10.5, fontWeight: 700, padding: "2px 8px", borderRadius: 20,
                      background: preview.classification.confidence >= 60 ? "rgba(16,185,129,0.2)" : preview.classification.confidence >= 40 ? "rgba(234,179,8,0.2)" : "rgba(239,68,68,0.18)",
                      color: preview.classification.confidence >= 60 ? "#34d399" : preview.classification.confidence >= 40 ? "#facc15" : "#f87171",
                      border: "1px solid rgba(255,255,255,0.15)",
                    }}>
                      {preview.classification.confidence > 0 ? `${preview.classification.confidence}% confidence` : "unclassified"}
                    </span>
                    {preview.classification.ambiguous && (
                      <span style={{ fontSize: 10.5, color: "#fbbf24" }}>review the template</span>
                    )}
                  </div>
                  <ul style={{ margin: "8px 0 0 0", paddingLeft: 16, fontSize: 12, color: "#d4d4d8", lineHeight: 1.6 }}>
                    {preview.classification.reasons.slice(0, 4).map((reason) => <li key={reason}>{reason}</li>)}
                  </ul>
                </div>
              </div>
              <div style={{ minWidth: 240 }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, color: "#a1a1aa", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                  Analysis template
                </div>
                <select
                  value={schemaChoice}
                  onChange={(event) => handleSchemaChange(event.target.value)}
                  style={{ width: "100%", background: "#18181b", color: "#ffffff", border: "1px solid #3f3f46", borderRadius: 8, padding: "8px 10px", fontSize: 12.5, fontFamily: "inherit" }}
                >
                  <option value="auto">Auto-detect ({preview.classification.label})</option>
                  {templates.map((template) => (
                    <option key={template.id} value={template.id}>{template.label}</option>
                  ))}
                </select>
                <div style={{ fontSize: 11, color: "#a1a1aa", marginTop: 6 }}>
                  {templates.find((template) => template.id === schemaChoice)?.description || preview.schema.description}
                </div>
              </div>
            </div>
          </div>

          {/* Profile tiles */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginBottom: 14 }}>
            {[
              { label: "Rows", value: preview.profile.rows.toLocaleString() },
              { label: "Columns", value: String(preview.profile.columns) },
              { label: "Missing cells", value: `${preview.profile.missing_pct.toFixed(1)}%` },
              { label: "Duplicate rows", value: preview.profile.duplicate_rows.toLocaleString() },
              { label: "Numeric", value: String(preview.profile.type_counts.numeric || 0) },
            ].map((tile) => (
              <div key={tile.label} className="panel panel-body" style={{ padding: "12px 14px" }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{tile.label}</div>
                <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: -0.5 }}>{tile.value}</div>
              </div>
            ))}
          </div>

          {/* Task & target */}
          <div className="panel panel-body" style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <Target size={15} />
              <span style={{ fontSize: 13, fontWeight: 800 }}>Analysis to prepare</span>
              <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>only supported tasks can be selected</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-secondary)", marginBottom: 5 }}>TASK</div>
                <select
                  value={task}
                  onChange={(event) => handleTaskChange(event.target.value)}
                  style={{ width: "100%", background: "#ffffff", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px", fontSize: 12.5, fontFamily: "inherit" }}
                >
                  {taskOptions.map((option) => (
                    <option key={option.key} value={option.key} disabled={!option.available}>
                      {option.label}
                      {option.available ? "" : ` — unavailable: ${option.reason || "insufficient data"}`}
                    </option>
                  ))}
                </select>
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 5, lineHeight: 1.5 }}>
                  {taskOptions.find((option) => option.key === task)?.reason}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-secondary)", marginBottom: 5 }}>TARGET COLUMN</div>
                <select
                  value={target || ""}
                  onChange={(event) => setTarget(event.target.value || null)}
                  disabled={task === "eda" || task === "clustering"}
                  style={{ width: "100%", background: "#ffffff", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px", fontSize: 12.5, fontFamily: "inherit", color: task === "eda" || task === "clustering" ? "var(--text-muted)" : "inherit" }}
                >
                  <option value="">{task === "eda" || task === "clustering" ? "not required for this task" : "— select a target —"}</option>
                  {targetOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 5 }}>
                  {targetOptions.find((option) => option.value === target)?.reason || "Choose the column the model should explain."}
                </div>
              </div>
            </div>
          </div>

          {/* Mapping */}
          <div className="panel panel-body" style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 800, marginBottom: 3 }}>Column mapping</div>
                <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  {mappedCount} mapped · {derivedCount} derived/generated · {rows.length - mappedCount - derivedCount} not mapped
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="btn-ghost" style={{ fontSize: 11 }} onClick={() => setShowOptional((value) => !value)}>
                  {showOptional ? "Hide" : "Show"} optional fields{hiddenOptional && !showOptional ? ` (+${hiddenOptional})` : ""}
                </button>
                <button
                  className="btn-ghost" style={{ fontSize: 11 }}
                  onClick={() => { setOverrides({}); setError(""); }}
                  title="Discard manual changes and use the automatic suggestions"
                >
                  <RefreshCw size={12} /> Reset to suggestions
                </button>
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {visibleRows.map(({ decision, value, override, status }) => {
                const column = columnByName(preview, value);
                const isDerived = status === "derived";
                const isGenerated = status === "generated";
                return (
                  <div key={decision.field} style={{
                    border: `1px solid ${status === "invalid" ? "#fecaca" : isDerived ? "#c7d2fe" : "var(--border)"}`,
                    background: isDerived ? "#fafaff" : "#fbfbfb",
                    borderRadius: 9, padding: "10px 12px",
                  }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "flex-start", flexWrap: "wrap" }}>
                      <div style={{ flex: "1 1 210px", minWidth: 190 }}>
                        <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--text-secondary)", marginBottom: 2 }}>
                          {decision.label}
                          {decision.required && <span style={{ color: "#dc2626", marginLeft: 3 }}>✱</span>}
                          <span style={{ marginLeft: 6, fontWeight: 500, color: "var(--text-muted)" }}>{DTYPE_LABEL[decision.dtype] || decision.dtype}</span>
                        </div>
                        <div style={{ fontSize: 10.5, color: "var(--text-muted)", lineHeight: 1.45 }}>{decision.description}</div>
                      </div>

                      <div style={{ flex: "2 1 300px", minWidth: 240 }}>
                        {isDerived ? (
                          <div style={{ fontSize: 12, color: "#4338ca", background: "#eef2ff", border: "1px solid #c7d2fe", borderRadius: 6, padding: "7px 9px" }}>
                            Computed from {decision.derived_from.length ? decision.derived_from.join(", ") : "mapped source fields"} — no source column needed.
                          </div>
                        ) : isGenerated ? (
                          <div style={{ fontSize: 12, color: "#475569", background: "#f1f5f9", border: "1px solid #e2e8f0", borderRadius: 6, padding: "7px 9px" }}>
                            No source identifier found. A labelled technical row index will be created (not a business measurement).
                          </div>
                        ) : (
                          <select
                            value={value}
                            onChange={(event) => setOverrides((current) => ({ ...current, [decision.field]: event.target.value }))}
                            style={{
                              width: "100%", background: "#ffffff",
                              border: `1px solid ${status === "invalid" ? "#fca5a5" : status === "needs_review" ? "#fcd34d" : "var(--border)"}`,
                              borderRadius: 6, fontSize: 12.5, padding: "7px 9px",
                              fontFamily: "inherit", color: value ? "var(--text-primary)" : "var(--text-muted)",
                            }}
                          >
                            <option value="">— not mapped —</option>
                            {preview.columns.map((columnName) => (
                              <option key={columnName} value={columnName}>{columnName}</option>
                            ))}
                            {decision.allow_generated && (
                              <option value="__generate__">Generated index (technical identifier only)</option>
                            )}
                          </select>
                        )}
                        {column && (
                          <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {DTYPE_LABEL[column.dtype] || column.dtype} · {column.unique.toLocaleString()} distinct · {column.missing_pct.toFixed(1)}% missing
                            {column.sample_values.length ? ` · e.g. ${column.sample_values.slice(0, 3).join(", ")}` : ""}
                          </div>
                        )}
                      </div>

                      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, minWidth: 96 }}>
                        <StatusChip kind={status} />
                        <span style={{ fontSize: 10.5, color: "var(--text-muted)", fontWeight: 600 }}>
                          {isDerived || isGenerated ? "—" : override ? "user selected" : decision.confidence === "high" ? "high confidence" : decision.confidence === "medium" ? "medium confidence" : decision.confidence === "low" ? "low confidence" : "—"}
                        </span>
                      </div>

                      <button
                        onClick={() => setExpanded(expanded === decision.field ? null : decision.field)}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", padding: 2 }}
                        title="Why this match?"
                      >
                        <Info size={14} />
                      </button>
                    </div>

                    {expanded === decision.field && (
                      <div style={{ marginTop: 8, borderTop: "1px solid var(--border)", paddingTop: 8, fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.55 }}>
                        <div><strong>Evidence:</strong> {decision.reasons.join("; ")}</div>
                        {decision.alternatives.filter((alt) => alt.column !== value).length > 0 && (
                          <div style={{ marginTop: 3 }}>
                            <strong>Other candidates:</strong>{" "}
                            {decision.alternatives.filter((alt) => alt.column !== value).slice(0, 3).map((alt) => `${alt.column} (${(alt.score * 100).toFixed(0)}%)`).join(", ")}
                          </div>
                        )}
                        {decision.sample_values.length > 0 && (
                          <div style={{ marginTop: 3 }}><strong>Sample values:</strong> {decision.sample_values.slice(0, 5).join(", ")}</div>
                        )}
                        <div style={{ marginTop: 3 }}><strong>Score:</strong> {(decision.score * 100).toFixed(0)}%</div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {hiddenOptional > 0 && !showOptional && (
              <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 10 }}>
                {hiddenOptional} optional field(s) are unmapped and hidden. Use the toggle above to review them.
              </div>
            )}
          </div>

          {/* Validation */}
          <div className="panel panel-body" style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <ListChecks size={16} />
                <span style={{ fontSize: 13.5, fontWeight: 800 }}>Validation</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, fontWeight: 700, color: ready ? "#059669" : "#b91c1c" }}>
                <ShieldCheck size={14} />
                {ready ? "Ready to ingest" : `${counts.errors} blocking issue${counts.errors === 1 ? "" : "s"}`}
                {counts.warnings > 0 && <span style={{ color: "#92400e", fontWeight: 500 }}>· {counts.warnings} warning{counts.warnings === 1 ? "" : "s"}</span>}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {checks.filter((check) => check.status !== "pass" || check.id === "rows" || check.id === "task:forecast").slice(0, 12).map((check) => {
                const tone = checkTone(check.status);
                return (
                  <div key={check.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, background: tone.bg, border: `1px solid ${tone.border}`, borderRadius: 7, padding: "7px 10px", color: tone.color, fontSize: 11.5, lineHeight: 1.5 }}>
                    <span style={{ marginTop: 1 }}>{tone.icon}</span>
                    <span><strong>{check.label}:</strong> {check.detail}</span>
                  </div>
                );
              })}
              {checks.every((check) => check.status === "pass") && (
                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#065f46", fontSize: 12 }}>
                  <CheckCircle2 size={14} /> All required mappings, types and task conditions passed.
                </div>
              )}
            </div>
            {serverChecks.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 11.5, fontWeight: 700, marginBottom: 6, color: "#b91c1c" }}>Server validation errors</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  {serverChecks.filter((check) => check.status === "fail").map((check) => (
                    <div key={`server-${check.id}`} style={{ fontSize: 11.5, color: "#b91c1c" }}>
                      • <strong>{check.label}:</strong> {check.detail}
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 10 }}>
              These checks run in the browser from the file profile. The server re-validates the final mapping and refuses to write invalid data.
            </div>
          </div>

          {/* Preview */}
          <div className="panel" style={{ marginBottom: 14, overflow: "hidden" }}>
            <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
              <Eye size={14} />
              <span style={{ fontSize: 12.5, fontWeight: 800 }}>Source preview</span>
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>first {preview.preview.length} rows, exactly as uploaded</span>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>{preview.columns.slice(0, 8).map((column) => <th key={column}>{column}</th>)}</tr>
                </thead>
                <tbody>
                  {preview.preview.map((row, index) => (
                    <tr key={index}>
                      {preview.columns.slice(0, 8).map((column) => (
                        <td key={column} style={{ maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {row[column] || "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", flexWrap: "wrap", marginBottom: 24 }}>
            <button className="btn-ghost" onClick={reset}>Start over</button>
            <button
              className="btn-primary"
              onClick={handleCommit}
              disabled={committing || !ready}
              style={{ padding: "10px 26px", opacity: ready ? 1 : 0.55, cursor: ready ? "pointer" : "not-allowed" }}
              title={ready ? "Validate on the server and load this dataset" : "Resolve the blocking validation issues first"}
            >
              {committing ? <><Loader size={14} style={{ animation: "spin 1s linear infinite" }} /> Loading…</> : <>Load into BIDS <ArrowRight size={14} /></>}
            </button>
          </div>
        </div>
      )}

      {/* ── Step 3: loading ─────────────────────────────────────────────────── */}
      {step === "loading" && (
        <div className="animate-fade-up" style={{ opacity: 0, textAlign: "center", padding: "64px 0" }}>
          <div style={{ width: 72, height: 72, borderRadius: "50%", background: "#f3f4f6", border: "2px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 24px" }}>
            <Loader size={28} style={{ animation: "spin 1s linear infinite" }} />
          </div>
          <div style={{ fontSize: 19, fontWeight: 800, marginBottom: 6 }}>Validating and loading</div>
          <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            Re-checking types and required fields, storing the dataset and rebuilding only what it supports.
          </div>
        </div>
      )}

      {/* ── Step 4: done ────────────────────────────────────────────────────── */}
      {step === "done" && result && (
        <div className="animate-fade-up" style={{ opacity: 0 }}>
          <div className="panel panel-body" style={{ textAlign: "center", padding: "44px 28px", marginBottom: 14 }}>
            <div style={{ width: 68, height: 68, borderRadius: "50%", background: "#000000", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px" }}>
              <CheckCircle2 size={30} color="#ffffff" />
            </div>
            <div style={{ fontSize: 22, fontWeight: 800, marginBottom: 4 }}>Dataset loaded</div>
            <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 22, maxWidth: 520, marginLeft: "auto", marginRight: "auto", lineHeight: 1.6 }}>
              {result.message}
            </div>
            <div style={{ display: "flex", justifyContent: "center", gap: 28, flexWrap: "wrap", marginBottom: 22 }}>
              {[
                { label: "Rows stored", value: result.rows_loaded.toLocaleString() },
                { label: "Rows skipped", value: result.rows_skipped.toLocaleString() },
                { label: "Warnings", value: String(result.warnings) },
              ].map((tile) => (
                <div key={tile.label} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: -0.8 }}>{tile.value}</div>
                  <div style={{ fontSize: 11.5, color: "var(--text-secondary)", fontWeight: 600 }}>{tile.label}</div>
                </div>
              ))}
            </div>
            <div style={{ display: "inline-flex", gap: 8, alignItems: "center", fontSize: 11.5, background: "#f3f4f6", border: "1px solid var(--border)", borderRadius: 6, padding: "5px 10px", marginBottom: 20 }}>
              <Layers size={12} /> {result.schema_label} · {result.task}{result.target ? ` · ${result.target}` : ""}
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
              <a href="/analysis" className="btn-primary" style={{ padding: "10px 22px", fontSize: 13, textDecoration: "none" }}>
                Open Analysis Report <ArrowRight size={14} />
              </a>
              {result.modules?.dashboard && (
                <a href="/dashboard" className="btn-ghost" style={{ padding: "10px 20px", fontSize: 13, textDecoration: "none" }}>Executive Dashboard</a>
              )}
              {result.modules?.behavior && (
                <a href="/behavior" className="btn-ghost" style={{ padding: "10px 20px", fontSize: 13, textDecoration: "none" }}>Behavior</a>
              )}
              {result.modules?.segmentation && (
                <a href="/segmentation" className="btn-ghost" style={{ padding: "10px 20px", fontSize: 13, textDecoration: "none" }}>Segmentation</a>
              )}
              <button className="btn-ghost" onClick={reset}>Upload another</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
