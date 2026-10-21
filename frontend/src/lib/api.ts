import axios from "axios";

const API = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
});

export const getDashboard   = () => API.get("/api/dashboard").then(r => r.data);
export const getBehavior    = () => API.get("/api/behavior").then(r => r.data);
export const getSegments    = () => API.get("/api/segments").then(r => r.data);
export const getRootCause   = () => API.get("/api/rootcause").then(r => r.data);
export const getDrift       = () => API.get("/api/drift").then(r => r.data);
export const getForecast    = () => API.get("/api/forecast").then(r => r.data);
export const postWhatIf     = (body: { price_change: number; discount_change: number; marketing_boost: number }) =>
  API.post("/api/forecast/whatif", body).then(r => r.data);
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
