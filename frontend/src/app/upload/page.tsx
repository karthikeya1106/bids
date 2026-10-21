"use client";
import { useState, useRef, useCallback, useEffect } from "react";
import {
  Upload, FileSpreadsheet, CheckCircle2, AlertCircle,
  ArrowRight, RotateCcw, Database, ChevronRight, Loader, X,
} from "lucide-react";
import { previewUpload, commitUpload, getUploadStatus } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────
interface BidsField { required: boolean; label: string; }
interface PreviewData {
  filename: string;
  total_rows: number;
  columns: string[];
  preview: Record<string, string>[];
  auto_mapping: Record<string, string>;
  fields: Record<string, BidsField>;
}
interface CommitResult {
  success: boolean;
  rows_loaded: number;
  rows_failed: number;
  customers_loaded: number;
  message: string;
}
interface UploadStatus {
  has_data: boolean;
  order_count: number;
  customer_count: number;
  date_range: { from: string | null; to: string | null };
  total_sales: number;
}

type Step = "upload" | "map" | "commit" | "done";

const FIELD_ORDER = [
  "order_id", "order_date", "customer_id", "sales",
  "profit", "quantity", "discount", "ship_date",
  "customer_name", "segment", "category", "sub_category",
  "product_name", "region", "city", "state",
];

export default function UploadPage() {
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [orgName, setOrgName] = useState("");
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [result, setResult] = useState<CommitResult | null>(null);
  const [status, setStatus] = useState<UploadStatus | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getUploadStatus().then(setStatus).catch(() => {});
  }, []);

  // ── Drag & drop ─────────────────────────────────────────────────────────────
  const onDragOver  = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragging(true); }, []);
  const onDragLeave = useCallback(() => setDragging(false), []);
  const onDrop      = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, []); // eslint-disable-line

  const handleFile = (f: File) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!["csv", "xlsx", "xls"].includes(ext || "")) {
      setError("Only CSV or Excel (.xlsx/.xls) files are supported.");
      return;
    }
    setError("");
    setFile(f);
  };

  // ── Step 1 → Step 2: Preview ────────────────────────────────────────────────
  const handlePreview = async () => {
    if (!file) return;
    setLoading(true); setError("");
    try {
      const data: PreviewData = await previewUpload(file);
      setPreview(data);
      setMapping(data.auto_mapping);
      setStep("map");
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to read file.");
    } finally {
      setLoading(false);
    }
  };

  // ── Step 3: Commit ───────────────────────────────────────────────────────────
  const handleCommit = async () => {
    if (!file || !preview) return;
    // Validate required fields
    for (const field of ["order_id", "order_date", "customer_id", "sales"]) {
      if (!mapping[field]) {
        setError(`Required field "${preview.fields[field]?.label}" is not mapped.`);
        return;
      }
    }
    setStep("commit");
    setLoading(true); setError("");
    try {
      const res: CommitResult = await commitUpload(file, mapping, orgName.trim() || undefined);
      setResult(res);
      setStep("done");
      // Refresh sidebar status
      getUploadStatus().then(setStatus).catch(() => {});
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Upload failed.");
      setStep("map");
    } finally {
      setLoading(false);
    }
  };

  // ── Reset ─────────────────────────────────────────────────────────────────
  const reset = () => {
    setStep("upload"); setFile(null); setPreview(null);
    setMapping({}); setResult(null); setError(""); setOrgName("");
  };

  // ── Render helpers ───────────────────────────────────────────────────────
  const StepDot = ({ s, label }: { s: Step; label: string }) => {
    const steps: Step[] = ["upload", "map", "commit", "done"];
    const idx = steps.indexOf(s);
    const cur = steps.indexOf(step);
    const done = cur > idx;
    const active = cur === idx;
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 28, height: 28, borderRadius: "50%",
          border: `2px solid ${done ? "#000000" : active ? "#000000" : "#d1d5db"}`,
          background: done ? "#000000" : active ? "#f3f4f6" : "transparent",
          display: "flex", alignItems: "center", justifyContent: "center",
          flexShrink: 0,
          transition: "all 0.3s ease",
        }}>
          {done
            ? <CheckCircle2 size={15} color="#ffffff" />
            : <span style={{ fontSize: 11, fontWeight: 800, color: active ? "#000000" : "#6b7280" }}>{idx + 1}</span>
          }
        </div>
        <span style={{ fontSize: 12.5, fontWeight: active ? 700 : 500, color: active ? "#000000" : done ? "#374151" : "#9ca3af" }}>
          {label}
        </span>
      </div>
    );
  };

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div className="page-title">
          <div className="page-title-icon">
            <Upload size={18} />
          </div>
          Data Upload
        </div>
        <p className="page-subtitle">
          Upload your company&apos;s sales data — CSV or Excel — and BIDS will power all 6 analytics modules with it instantly.
        </p>
      </div>

      {/* Current DB Status */}
      {status?.has_data && (
        <div className="panel panel-body animate-fade-up" style={{
          marginBottom: 16, opacity: 0,
          display: "flex", alignItems: "center", gap: 16,
          borderLeft: "4px solid #000000",
        }}>
          <Database size={18} style={{ color: "#000000", flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-primary)", marginBottom: 2 }}>
              Current Dataset
            </div>
            <div style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
              {status.order_count.toLocaleString()} orders · {status.customer_count.toLocaleString()} customers ·
              {" "}${status.total_sales.toLocaleString()} total sales ·
              {status.date_range.from && ` ${status.date_range.from} → ${status.date_range.to}`}
            </div>
          </div>
          <div style={{ fontSize: 10.5, fontWeight: 800, color: "#000000", background: "#f3f4f6",
            border: "1px solid var(--border)", borderRadius: 6, padding: "4px 10px" }}>
            LIVE
          </div>
        </div>
      )}

      {/* Step progress */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 16, opacity: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <StepDot s="upload" label="Upload File" />
          <ChevronRight size={13} style={{ color: "#9ca3af" }} />
          <StepDot s="map"    label="Map Columns" />
          <ChevronRight size={13} style={{ color: "#9ca3af" }} />
          <StepDot s="commit" label="Loading Data" />
          <ChevronRight size={13} style={{ color: "#9ca3af" }} />
          <StepDot s="done"   label="Done" />
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "12px 14px", background: "#fef2f2",
          border: "1px solid #fecaca", borderRadius: 10,
          marginBottom: 14, fontSize: 13, color: "#dc2626", fontWeight: 500,
        }}>
          <AlertCircle size={16} />
          {error}
          <button onClick={() => setError("")} style={{ marginLeft: "auto", background: "none", border: "none", color: "#dc2626", cursor: "pointer" }}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* ── STEP 1: Upload ────────────────────────────────────────────────── */}
      {step === "upload" && (
        <div className="animate-fade-up" style={{ opacity: 0 }}>
          {/* Org Name Input */}
          <div className="panel panel-body" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--text-secondary)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Organization Name <span style={{ color: "var(--text-muted)", fontWeight: 400, textTransform: "none" }}>(optional)</span>
            </div>
            <input
              id="org-name-input"
              type="text"
              value={orgName}
              onChange={e => setOrgName(e.target.value)}
              placeholder="e.g. Acme Corp, Retail Co, My Business…"
              style={{
                width: "100%", background: "#ffffff",
                border: "1px solid var(--border)", borderRadius: 8,
                color: "var(--text-primary)", fontSize: 13,
                padding: "10px 14px", fontFamily: "inherit", outline: "none",
                boxSizing: "border-box",
              }}
            />
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
              Tag this dataset to your organization — shown in the Analysis Report header.
            </div>
          </div>
          <div
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            onClick={() => fileRef.current?.click()}
            style={{
              border: `2px dashed ${dragging ? "#000000" : file ? "#4b5563" : "#d1d5db"}`,
              borderRadius: 16,
              padding: "52px 32px",
              textAlign: "center",
              cursor: "pointer",
              background: dragging ? "#f3f4f6" : "#ffffff",
              transition: "all 0.2s ease",
              boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
            }}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              style={{ display: "none" }}
              onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])}
            />
            <div style={{
              width: 56, height: 56, borderRadius: 14,
              background: "#000000", color: "#ffffff",
              display: "flex", alignItems: "center", justifyContent: "center",
              margin: "0 auto 20px",
              boxShadow: "0 4px 14px rgba(0,0,0,0.15)",
            }}>
              {file
                ? <FileSpreadsheet size={24} />
                : <Upload size={24} />
              }
            </div>

            {file ? (
              <>
                <div style={{ fontSize: 16, fontWeight: 800, color: "#000000", marginBottom: 6 }}>
                  {file.name}
                </div>
                <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 24 }}>
                  {(file.size / 1024).toFixed(1)} KB · Click to change file
                </div>
                <button
                  className="btn-primary"
                  onClick={e => { e.stopPropagation(); handlePreview(); }}
                  disabled={loading}
                  style={{ fontSize: 13, padding: "10px 28px" }}
                >
                  {loading ? <><Loader size={14} style={{ animation: "spin 1s linear infinite" }} /> Analysing…</> : <>Analyse File <ArrowRight size={14} /></>}
                </button>
              </>
            ) : (
              <>
                <div style={{ fontSize: 17, fontWeight: 800, color: "#000000", marginBottom: 8 }}>
                  Drop your sales file here
                </div>
                <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 6 }}>
                  or click to browse from your computer
                </div>
                <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                  Supports: CSV, Excel (.xlsx, .xls) — any size
                </div>
              </>
            )}
          </div>

          {/* Accepted formats info */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 16 }}>
            {[
              { label: "Kaggle Superstore",    cols: "order_id, sales, profit, customer_id, category …" },
              { label: "Shopify / WooCommerce",cols: "Order, Revenue, Customer, Product …" },
              { label: "Any Sales CSV",         cols: "Any column names — you map them in step 2" },
            ].map(({ label, cols }) => (
              <div key={label} className="panel panel-body" style={{ padding: "12px 14px" }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>{cols}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── STEP 2: Map Columns ───────────────────────────────────────────── */}
      {step === "map" && preview && (
        <div className="animate-fade-up" style={{ opacity: 0 }}>
          {/* File info */}
          <div className="panel panel-body" style={{ marginBottom: 14, display: "flex", alignItems: "center", gap: 12 }}>
            <FileSpreadsheet size={18} style={{ color: "#000000" }} />
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 13.5, fontWeight: 700, color: "var(--text-primary)" }}>{preview.filename}</span>
              <span style={{ fontSize: 11.5, color: "var(--text-muted)", marginLeft: 10 }}>
                {preview.total_rows.toLocaleString()} rows · {preview.columns.length} columns
              </span>
            </div>
            <button className="btn-ghost" style={{ fontSize: 11 }} onClick={reset}>
              <RotateCcw size={12} /> Change file
            </button>
          </div>

          {/* Column mapping */}
          <div className="panel panel-body" style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 13.5, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>
              Map Your Columns
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 18 }}>
              We auto-detected the mappings below. Review and adjust if needed. Required fields are marked ✱
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {FIELD_ORDER.map(field => {
                const meta = preview.fields[field];
                if (!meta) return null;
                return (
                  <div key={field} style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "10px 12px",
                    background: "#f9fafb", borderRadius: 8,
                    border: meta.required && !mapping[field]
                      ? "1px solid #f87171"
                      : "1px solid var(--border)",
                  }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--text-secondary)", marginBottom: 4 }}>
                        {meta.label}
                        {meta.required && <span style={{ color: "#dc2626", marginLeft: 3 }}>✱</span>}
                      </div>
                      <select
                        value={mapping[field] || ""}
                        onChange={e => setMapping(m => ({ ...m, [field]: e.target.value }))}
                        style={{
                          width: "100%", background: "#ffffff",
                          border: "1px solid var(--border)", borderRadius: 6,
                          color: mapping[field] ? "var(--text-primary)" : "var(--text-muted)",
                          fontSize: 12.5, padding: "6px 8px",
                          fontFamily: "inherit", cursor: "pointer", outline: "none",
                        }}
                      >
                        <option value="">— not mapped —</option>
                        {preview.columns.map(col => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>
                    {mapping[field] && (
                      <CheckCircle2 size={16} color="#059669" style={{ flexShrink: 0 }} />
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* 5-row preview */}
          <div className="panel" style={{ marginBottom: 14, overflow: "hidden" }}>
            <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
              <span style={{ fontSize: 13, fontWeight: 800, color: "var(--text-primary)" }}>Data Preview</span>
              <span style={{ fontSize: 11.5, color: "var(--text-muted)", marginLeft: 8 }}>First 5 rows</span>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    {preview.columns.slice(0, 8).map(col => (
                      <th key={col}>{col}</th>
                    ))}
                    {preview.columns.length > 8 && <th>+{preview.columns.length - 8} more</th>}
                  </tr>
                </thead>
                <tbody>
                  {preview.preview.map((row, i) => (
                    <tr key={i}>
                      {preview.columns.slice(0, 8).map(col => (
                        <td key={col} style={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {row[col] || "—"}
                        </td>
                      ))}
                      {preview.columns.length > 8 && <td style={{ color: "var(--text-muted)" }}>…</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Actions */}
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button className="btn-ghost" onClick={reset}>Start over</button>
            <button className="btn-primary" onClick={handleCommit} style={{ padding: "10px 28px" }}>
              Load into BIDS <ArrowRight size={14} />
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 3: Loading ───────────────────────────────────────────────── */}
      {step === "commit" && (
        <div className="animate-fade-up" style={{ opacity: 0, textAlign: "center", padding: "64px 0" }}>
          <div style={{
            width: 72, height: 72, borderRadius: "50%",
            background: "#f3f4f6", border: "2px solid var(--border)",
            display: "flex", alignItems: "center", justifyContent: "center",
            margin: "0 auto 28px",
          }}>
            <Loader size={28} color="#000000" style={{ animation: "spin 1s linear infinite" }} />
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "#000000", marginBottom: 8 }}>
            Loading your data into PostgreSQL…
          </div>
          <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            Transforming columns, building customer profiles, inserting orders.
          </div>
        </div>
      )}

      {/* ── STEP 4: Done ──────────────────────────────────────────────────── */}
      {step === "done" && result && (
        <div className="animate-fade-up" style={{ opacity: 0 }}>
          <div className="panel panel-body" style={{ textAlign: "center", padding: "48px 32px", marginBottom: 16 }}>
            <div style={{
              width: 72, height: 72, borderRadius: "50%",
              background: "#000000",
              display: "flex", alignItems: "center", justifyContent: "center",
              margin: "0 auto 24px",
              boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
            }}>
              <CheckCircle2 size={32} color="#ffffff" />
            </div>
            <div style={{ fontSize: 24, fontWeight: 800, color: "#000000", marginBottom: 4, letterSpacing: -0.4 }}>
              Data loaded successfully!
            </div>
            {(result as any).org_name && (
              <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 4 }}>
                Organization: <strong style={{ color: "#000000" }}>{(result as any).org_name}</strong>
              </div>
            )}
            <div style={{ fontSize: 13.5, color: "var(--text-muted)", marginBottom: 32 }}>
              {result.message}
            </div>
            <div style={{ display: "flex", justifyContent: "center", gap: 32, marginBottom: 32 }}>
              {[
                { label: "Orders Loaded",    value: result.rows_loaded.toLocaleString() },
                { label: "Customers",        value: result.customers_loaded.toLocaleString() },
                { label: "Rows Failed",      value: result.rows_failed.toLocaleString() },
              ].map(({ label, value }) => (
                <div key={label} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 30, fontWeight: 800, color: "#000000", letterSpacing: -1 }}>{value}</div>
                  <div style={{ fontSize: 11.5, color: "var(--text-secondary)", fontWeight: 600 }}>{label}</div>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
              <a href="/analysis" className="btn-primary" style={{ padding: "11px 28px", fontSize: 13 }}>
                Run Deep Analysis <ArrowRight size={14} />
              </a>
              <a href="/dashboard" className="btn-ghost" style={{ padding: "11px 22px", fontSize: 13 }}>
                View Dashboard
              </a>
              <button className="btn-ghost" onClick={reset}>Upload another file</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
