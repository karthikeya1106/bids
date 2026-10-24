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
export const getDrift       = () => API.get("/api/drift").then(r => r.data);
export const getForecast    = (horizon = 6) =>
  API.get("/api/forecast", { params: { horizon } }).then(r => r.data);
export const postWhatIf     = (body: {
  price_change: number;
  discount_change: number;
  marketing_boost: number;
  horizon_months?: number;
}) => API.post("/api/forecast/whatif", body).then(r => r.data);
export const getStrategyInsights = () => API.get("/api/strategy/insights").then(r => r.data);
export const postStrategy   = () => API.post("/api/strategy").then(r => r.data);
export const patchRule      = (id: number, body: { status?: string; rule_description?: string; action?: string }) =>
  API.patch(`/api/drift/rules/${id}`, body).then(r => r.data);

// ── Data Upload ──────────────────────────────────────────────────────────────
export const getUploadStatus = () => API.get("/api/upload/status").then(r => r.data);

export const previewUpload = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return API.post("/api/upload/preview", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then(r => r.data);
};

export const commitUpload = (file: File, mapping: Record<string, string>, orgName?: string) => {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("mapping", JSON.stringify(mapping));
  if (orgName) fd.append("org_name", orgName);
  return API.post("/api/upload/commit", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then(r => r.data);
};

// ── Analysis Report ──────────────────────────────────────────────────────────
export const getAnalysisReport = () => API.get("/api/analysis/report").then(r => r.data);
export const getHealthScore    = () => API.get("/api/analysis/health-score").then(r => r.data);

export default API;
