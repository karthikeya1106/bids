"use client";
import { useState } from "react";
import { CheckCircle2, Loader, Target, Trash2 } from "lucide-react";
import { setDatasetTarget } from "@/lib/api";

export interface TargetInfo {
  column: string;
  kind: "binary" | "multiclass" | "continuous";
  task: "classification" | "regression";
  confirmed: boolean;
  event?: string | null;
  event_share?: number | null;
  classes?: { label: string; count: number; share: number }[];
  reasons?: string[];
  polarity?: string | null;
}

export interface TargetSuggestion {
  column: string;
  kind: string;
  task: string;
  classes: number;
  reason: string;
  suggested?: boolean;
}

interface Props {
  datasetId?: number | null;
  target?: TargetInfo | null;
  suggestions?: TargetSuggestion[];
  onChanged?: () => void;
}

export default function TargetPicker({ datasetId, target, suggestions = [], onChanged }: Props) {
  const [choice, setChoice] = useState(target?.column || suggestions.find((s) => s.suggested)?.column || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!datasetId) return null;

  const candidates = Array.from(
    new Map(
      [
        ...(target ? [{ column: target.column, reason: "current target" }] : []),
        ...suggestions.map((s) => ({ column: s.column, reason: s.reason })),
      ].map((entry) => [entry.column, entry]),
    ).values(),
  );

  const apply = async (column: string | null) => {
    setBusy(true);
    setError("");
    try {
      await setDatasetTarget(datasetId, { target: column });
      onChanged?.();
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "Could not update the target.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="panel panel-body animate-fade-up"
      style={{ marginBottom: 16, opacity: 0, borderColor: target && !target.confirmed ? "#fcd34d" : "var(--border)" }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div
          style={{
            width: 34, height: 34, borderRadius: 9, background: target?.confirmed ? "#065f46" : "#92400e",
            color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
          }}
        >
          <Target size={16} />
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13.5, fontWeight: 800 }}>
              {target ? "Prediction target" : "No prediction target selected"}
            </span>
            {target?.confirmed && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10.5, fontWeight: 700, padding: "3px 8px", borderRadius: 5, background: "#ecfdf5", border: "1px solid #a7f3d0", color: "#065f46" }}>
                <CheckCircle2 size={11} /> Confirmed · {target.column}
              </span>
            )}
            {target && !target.confirmed && (
              <span style={{ fontSize: 10.5, fontWeight: 700, padding: "3px 8px", borderRadius: 5, background: "#fffbeb", border: "1px solid #fcd34d", color: "#92400e" }}>
                Suggested · {target.column}
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4, lineHeight: 1.55 }}>
            {target?.confirmed
              ? "Supervised analysis uses this column as the outcome. Metrics are measured on held-out rows."
              : target
                ? `Detected from the data: ${(target.reasons || []).join(" · ")}. Confirm it to enable supervised modelling; nothing is trained until you do.`
                : "Choose a column with 2–20 observed classes (or a numeric measure) to enable supervised analysis."}
          </div>
          {target?.polarity && !target.confirmed && (
            <div style={{ fontSize: 11.5, color: "#92400e", marginTop: 6 }}>{target.polarity}</div>
          )}
          {error && <div style={{ fontSize: 11.5, color: "#b91c1c", marginTop: 6 }}>{error}</div>}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {candidates.length > 1 && (
            <select
              value={choice}
              onChange={(event) => setChoice(event.target.value)}
              className="input"
              style={{ fontSize: 12, padding: "7px 10px", minWidth: 150, background: "#fff" }}
            >
              {candidates.map((entry) => (
                <option key={entry.column} value={entry.column}>{entry.column}</option>
              ))}
            </select>
          )}
          {!target?.confirmed ? (
            <button
              className="btn-primary"
              disabled={busy || !choice}
              onClick={() => apply(choice)}
              style={{ fontSize: 12, gap: 6 }}
            >
              {busy ? <Loader size={13} className="spin" /> : <Target size={13} />}
              Confirm target
            </button>
          ) : (
            <button className="btn-ghost" disabled={busy} onClick={() => apply(null)} style={{ fontSize: 12, gap: 6 }}>
              {busy ? <Loader size={13} /> : <Trash2 size={13} />} Clear target
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
