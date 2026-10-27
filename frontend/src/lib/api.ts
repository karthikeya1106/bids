import axios from "axios";

// Same-origin proxy: it attaches the signed identity of the NextAuth session,
// so the browser never talks to FastAPI directly and never sees the signing key.
const API = axios.create({
  baseURL: "/api/backend",
  withCredentials: true,
});

export const getDashboard   = (months = 12) => API.get(`/api/dashboard?months=${months}`).then(r => r.data);
export const getBehavior    = () => API.get("/api/behavior").then(r => r.data);
export const getSegments    = () => API.get("/api/segments").then(r => r.data);
export const getRootCause   = (month?: string) =>
  API.get("/api/rootcause", { params: month ? { month } : {} }).then(r => r.data);
export const getDrift       = (referenceId?: number) =>
  API.get("/api/drift", { params: referenceId ? { reference_id: referenceId } : {} }).then(r => r.data);
export const getForecast    = (horizon = 6) =>
  API.get("/api/forecast", { params: { horizon } }).then(r => r.data);
export const postWhatIf     = (body: {
  price_change: number;
  discount_change: number;
  marketing_boost: number;
  horizon_months?: number;
  marketing_spend?: number;
}) => API.post("/api/forecast/whatif", body).then(r => r.data);
export const getStrategyInsights = () => API.get("/api/strategy/insights").then(r => r.data);

// ── Lever optimiser ──────────────────────────────────────────────────────────
export interface OptimizerCandidate {
  price_change: number;
  discount_change: number;
  marketing_boost: number;
  revenue: number;
  revenue_impact: number;
  revenue_impact_pct: number;
  profit: number;
  profit_impact: number;
  profit_impact_pct: number;
  incremental_marketing_spend: number;
}

export interface OptimizerResult {
  has_data: boolean;
  error?: string;
  horizon_months: number;
  objective: string;
  baseline: { revenue: number; profit: number };
  best: OptimizerCandidate | null;
  best_unconstrained: OptimizerCandidate | null;
  constraint: { min_revenue_impact_pct: number } | null;
  alternatives: OptimizerCandidate[];
  tradeoff: {
    price_change: number; discount_change: number; marketing_boost: number;
    revenue_impact_pct: number; profit_impact: number;
  }[];
  search: {
    price_change: number[]; discount_change: number[];
    marketing_boost: number[]; combinations: number;
  };
  elasticity: { value?: number; value_used?: number; measured?: boolean; method?: string; band?: [number, number] };
  assumptions: Record<string, number | boolean | string | null>;
  notes: string[];
}

export const postOptimize = (body: {
  horizon_months?: number;
  marketing_spend?: number;
  max_price_change?: number;
  max_discount_cut?: number;
  max_marketing_boost?: number;
  min_revenue_impact_pct?: number;
}) => API.post("/api/forecast/optimize", body).then(r => r.data as OptimizerResult);
/** Evaluate each measured play as a demand-simulator scenario. */
export const postStrategyScenarios = (body: { horizon_months?: number; marketing_spend?: number }) =>
  API.post("/api/strategy/scenarios", body).then(r => r.data);
export const postStrategy   = () => API.post("/api/strategy").then(r => r.data);
export const patchRule      = (id: number, body: { status?: string; rule_description?: string; action?: string }) =>
  API.patch(`/api/drift/rules/${id}`, body).then(r => r.data);

// ── Data Upload ──────────────────────────────────────────────────────────────
export const getUploadStatus = () => API.get("/api/upload/status").then(r => r.data);

export interface MappingDecision {
  field: string;
  label: string;
  description: string;
  dtype: string;
  required: boolean;
  target: boolean;
  role: string;
  allow_generated?: boolean;
  value: string;
  column: string | null;
  score: number;
  confidence: string;
  status: string;
  reasons: string[];
  alternatives: { column: string; score: number }[];
  derived_from: string[];
  sample_values: (string | number | null)[];
  source_dtype?: string;
}

export interface ColumnProfile {
  name: string;
  label: string;
  dtype: string;
  missing: number;
  missing_pct: number;
  unique: number;
  unique_ratio: number;
  numeric_parse_pct: number;
  date_parse_pct: number;
  sample_values: (string | number | null)[];
  top_values: { value: string; count: number; share: number }[];
  mean?: number | null;
  min?: number | null;
  max?: number | null;
  malformed: number;
  flags: string[];
}

export interface ValidationCheck {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail" | "info";
  detail: string;
  field?: string | null;
  rows?: number | null;
}

export interface UploadValidation {
  ready: boolean;
  errors: number;
  warnings: number;
  checks: ValidationCheck[];
  target: string | null;
  task: string;
  forecast: { available: boolean; reasons?: string[]; frequency?: string; periods?: number } | null;
  capabilities: Record<string, boolean>;
  required_missing: string[];
  mapped_fields: number;
  total_fields: number;
}

export interface UploadPreview {
  filename: string;
  total_rows: number;
  columns: string[];
  preview: Record<string, string>[];
  profile: {
    rows: number; columns: number; duplicate_rows: number; missing_pct: number;
    type_counts: Record<string, number>;
    column_profiles: ColumnProfile[];
    quality: { id: string; level: string; column?: string | null; message: string }[];
    time_coverage: { column: string; from: string; to: string; frequency: string; periods: number; coverage: number } | null;
    correlations: { a: string; b: string; r: number; strength: string }[];
  };
  classification: {
    schema: string; label: string; description: string; confidence: number;
    ambiguous: boolean; reasons: string[];
    alternatives: { schema: string; label: string; score: number }[];
    targets: { column: string; task: string; classes: number | null; reason: string }[];
  };
  schema: { id: string; label: string; description: string; fields: { key: string; label: string; description: string; dtype: string; required: boolean }[] };
  analysis_type: string;
  mapping: Record<string, MappingDecision>;
  task: string;
  target: string | null;
  tasks: Record<string, { available: boolean; reason: string; target?: string }>;
  targets: { column: string; task: string; classes: number | null; reason: string }[];
  validation: UploadValidation;
  modules: Record<string, boolean>;
}

export const getTemplates = () => API.get("/api/upload/templates").then(r => r.data);

export const previewUpload = (
  file: File,
  options: { analysisType?: string; mapping?: Record<string, string>; task?: string; target?: string } = {},
) => {
  const fd = new FormData();
  fd.append("file", file);
  if (options.mapping) fd.append("mapping", JSON.stringify(options.mapping));
  if (options.task) fd.append("task", options.task);
  if (options.target) fd.append("target", options.target);
  return API.post(
    `/api/upload/preview?analysis_type=${options.analysisType || "auto"}`,
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  ).then(r => r.data as UploadPreview);
};

export const validateUpload = (
  file: File,
  body: { schema: string; mapping: Record<string, string>; task?: string; target?: string },
) => {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("schema", body.schema);
  fd.append("mapping", JSON.stringify(body.mapping));
  if (body.task) fd.append("task", body.task);
  if (body.target) fd.append("target", body.target);
  return API.post("/api/upload/validate", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then(r => r.data);
};

export const commitUpload = (
  file: File,
  body: { schema: string; mapping: Record<string, string>; orgName?: string; task?: string; target?: string },
) => {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("schema", body.schema);
  fd.append("mapping", JSON.stringify(body.mapping));
  if (body.orgName) fd.append("org_name", body.orgName);
  if (body.task) fd.append("task", body.task);
  if (body.target) fd.append("target", body.target);
  return API.post("/api/upload/commit", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then(r => r.data);
};

// ── Dataset registry ─────────────────────────────────────────────────────────
export interface DatasetSummary {
  id: number; name: string; org_name: string | null; schema: string;
  schema_label: string; task: string; target: string | null; rows: number;
  customers: number; total_sales: number; is_active: boolean;
  synthetic_identifiers: boolean; uploaded_at: string | null;
  confidence?: number | null;
  needs_review?: boolean;
  classified_at?: string | null;
  supported_tasks?: Record<string, { available: boolean; reason?: string }>;
}

/** Result of re-running the classifier on a dataset that is already stored. */
export interface ReclassifyResult {
  success: boolean;
  changed: boolean;
  status: "reclassified" | "remapped" | "refreshed" | "unchanged";
  message: string;
  dataset: DatasetSummary;
  before: { schema: string; schema_label: string; task: string; target: string | null; rows: number; confidence: number | null };
  after: { schema: string; schema_label: string; task: string; target: string | null; rows: number; confidence: number | null };
  classification?: {
    confidence: number | null; ambiguous: boolean; chosen_by: string;
    reasons: string[]; alternatives: { schema: string; label: string; score: number }[];
    detected_target: string | null; classified_at: string;
  };
  mapping?: { field: string; label: string; column: string | null; status: string; confidence: string; reasons: string[] }[];
  mapping_changes: { field: string; label: string; before: string; after: string; status: string | null; confidence: string | null }[];
  review: { kind: string; field?: string; column?: string; message: string }[];
  notes: string[];
  tasks?: Record<string, { available: boolean; reason?: string }>;
  rows_rewritten: number;
  source?: string;
}

export const getDatasets = () =>
  API.get("/api/datasets").then(r => r.data as {
    datasets: DatasetSummary[];
    active_id: number | null;
    templates?: { id: string; label: string }[];
  });
export const activateDataset = (id: number) =>
  API.post(`/api/datasets/${id}/activate`).then(r => r.data);
export const deleteDataset = (id: number) =>
  API.delete(`/api/datasets/${id}`).then(r => r.data);
export const reclassifyDataset = (id: number, template?: string) =>
  API.post(`/api/datasets/${id}/reclassify`, template ? { schema: template } : {}).then(r => r.data as ReclassifyResult);
export const getActiveCapabilities = () =>
  API.get("/api/datasets/active/capabilities").then(r => r.data);
export const setDatasetTarget = (id: number, body: { target: string | null; task?: string }) =>
  API.patch(`/api/datasets/${id}/target`, body).then(r => r.data);

// ── Analysis Report ──────────────────────────────────────────────────────────
export const getAnalysisReport = () => API.get("/api/analysis/report").then(r => r.data);
export const getHealthScore    = () => API.get("/api/analysis/health-score").then(r => r.data);

/** Download the report the page shows as a PDF or an Excel workbook. */
export async function exportAnalysisReport(format: "pdf" | "xlsx") {
  const response = await API.get(`/api/analysis/report/export.${format}`, { responseType: "blob" });
  const disposition = String(response.headers["content-disposition"] || "");
  const match = disposition.match(/filename="?([^";]+)"?/);
  return {
    blob: response.data as Blob,
    filename: match?.[1] || `bids-report.${format}`,
  };
}

export default API;
