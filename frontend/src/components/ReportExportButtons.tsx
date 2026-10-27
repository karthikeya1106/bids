"use client";
import { useState } from "react";
import { Download, FileSpreadsheet } from "lucide-react";
import { exportAnalysisReport } from "@/lib/api";

/**
 * Downloads the analysis report the page is showing, as a PDF or a workbook.
 * Both are rendered by the API from the same payload, so the file matches the
 * screen rather than a second computation.
 */
export default function ReportExportButtons() {
  const [busy, setBusy] = useState<"pdf" | "xlsx" | "">("");
  const [error, setError] = useState("");

  const download = async (format: "pdf" | "xlsx") => {
    if (busy) return;
    setBusy(format);
    setError("");
    try {
      const { blob, filename } = await exportAnalysisReport(format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("Export failed — reload the report and try again.");
    } finally {
      setBusy("");
    }
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      <button
        className="btn-ghost"
        onClick={() => download("pdf")}
        disabled={busy !== ""}
        style={{ fontSize: 12, gap: 6 }}
        title="Download this report as a PDF"
      >
        <Download size={13} /> {busy === "pdf" ? "Preparing…" : "PDF"}
      </button>
      <button
        className="btn-ghost"
        onClick={() => download("xlsx")}
        disabled={busy !== ""}
        style={{ fontSize: 12, gap: 6 }}
        title="Download this report as an Excel workbook"
      >
        <FileSpreadsheet size={13} /> {busy === "xlsx" ? "Preparing…" : "Excel"}
      </button>
      {error && <span style={{ fontSize: 11, color: "#b91c1c" }}>{error}</span>}
    </div>
  );
}
