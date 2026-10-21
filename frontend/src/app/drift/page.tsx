"use client";
import { useEffect, useState } from "react";
import { getDrift, patchRule } from "@/lib/api";
import { BarChart3, CheckCircle, AlertCircle, XCircle, Edit3, Save, Cpu } from "lucide-react";

const STATUS_CFG: any = {
  active:       { label: "Active",       color: "#059669", tagClass: "tag-success", icon: CheckCircle },
  needs_review: { label: "Needs Review", color: "#d97706", tagClass: "tag-warning", icon: AlertCircle },
  obsolete:     { label: "Obsolete",     color: "#dc2626", tagClass: "tag-danger",  icon: XCircle },
};

function RuleCard({ rule, onUpdate }: any) {
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState(rule.status);
  const [saving, setSaving] = useState(false);
  const cfg = STATUS_CFG[status] || STATUS_CFG.active;
  const Icon = cfg.icon;

  const handleSave = async () => {
    setSaving(true);
    try { await onUpdate(rule.id, { status }); setEditing(false); } finally { setSaving(false); }
  };

  const score = rule.effectiveness_score;
  const scoreColor = score > 0.6 ? "#059669" : score > 0.35 ? "#d97706" : "#dc2626";

  return (
    <div className="rule-card">
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
            <Icon size={14} style={{ color: cfg.color, flexShrink: 0 }} />
            <span style={{ fontWeight: 800, fontSize: 13.5, color: "var(--text-primary)" }}>{rule.rule_name}</span>
          </div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>{rule.rule_description}</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 7, flexShrink: 0 }}>
          <span className={`tag ${cfg.tagClass}`}>{cfg.label}</span>
          <button
            onClick={() => setEditing(!editing)}
            className="btn-ghost"
            style={{ padding: "4px 8px", fontSize: 11 }}
          >
            <Edit3 size={12} />
          </button>
        </div>
      </div>

      {/* Effectiveness bar */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 11.5 }}>
          <span style={{ color: "var(--text-muted)", fontWeight: 500 }}>Effectiveness</span>
          <span style={{ color: scoreColor, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
            {(score * 100).toFixed(0)}%
          </span>
        </div>
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{
              width: `${score * 100}%`,
              background: "#000000",
            }}
          />
        </div>
      </div>

      {/* IF/THEN code blocks */}
      <div
        className="rule-code"
        style={{ background: "#f9fafb", color: "#111111", marginBottom: 6, border: "1px solid var(--border)" }}
      >
        <span style={{ color: "#000000", fontWeight: 800 }}>IF </span>
        <span style={{ color: "var(--text-secondary)" }}>{rule.condition_expression}</span>
      </div>
      <div
        className="rule-code"
        style={{ background: "#f3f4f6", color: "#111111", border: "1px solid var(--border)" }}
      >
        <span style={{ color: "#000000", fontWeight: 800 }}>THEN </span>
        <span style={{ color: "var(--text-secondary)" }}>{rule.action}</span>
      </div>

      {/* Inline editor */}
      {editing && (
        <div
          style={{
            marginTop: 12, padding: 12, borderRadius: 10,
            background: "#f9fafb", border: "1px solid var(--border)",
          }}
        >
          <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)", marginBottom: 8, textTransform: "uppercase" }}>
            Update Status
          </div>
          <div style={{ display: "flex", gap: 7, marginBottom: 10, flexWrap: "wrap" }}>
            {(["active", "needs_review", "obsolete"] as const).map(s => {
              const scfg = STATUS_CFG[s];
              const isSelected = s === status;
              return (
                <button
                  key={s}
                  onClick={() => setStatus(s)}
                  className={isSelected ? "btn-primary" : "btn-ghost"}
                  style={{
                    padding: "4px 10px", fontSize: 11,
                  }}
                >
                  {scfg.label}
                </button>
              );
            })}
          </div>
          <button onClick={handleSave} disabled={saving} className="btn-primary" style={{ fontSize: 12 }}>
            <Save size={12} />
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      )}
    </div>
  );
}

export default function DriftPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { getDrift().then(setData).finally(() => setLoading(false)); }, []);

  const handleRuleUpdate = async (id: number, body: any) => {
    await patchRule(id, body);
    getDrift().then(setData);
  };

  if (loading) return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {[...Array(4)].map((_, i) => <div key={i} className="skeleton" style={{ height: 120, borderRadius: 14 }} />)}
    </div>
  );

  if (!data) return (
    <div style={{ textAlign: "center", padding: "80px 0", color: "var(--text-muted)" }}>
      Failed to load drift data.
    </div>
  );

  const summaryMetrics = [
    { label: "Active Rules",    value: data.active_rules },
    { label: "Needs Review",    value: data.rules_needing_review },
    { label: "Obsolete Rules",  value: data.obsolete_rules },
  ];

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div className="page-title">
          <div className="page-title-icon">
            <BarChart3 size={18} />
          </div>
          Data Drift & BPR Analytics
        </div>
        <p className="page-subtitle">Monitor KPI drift with River ADWIN and manage Business Process Rules</p>
      </div>

      {/* Summary KPIs */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 18 }}>
        {summaryMetrics.map((m, i) => (
          <div
            key={i}
            className="kpi-card animate-fade-up"
            style={{ textAlign: "center", animationDelay: `${i * 70}ms`, opacity: 0 }}
          >
            <div className="kpi-accent-bar" />
            <div className="kpi-value" style={{ fontSize: 36, marginTop: 12 }}>{m.value}</div>
            <div className="kpi-sub" style={{ marginTop: 6, fontWeight: 600 }}>{m.label}</div>
          </div>
        ))}
      </div>

      {/* KPI Drift Monitor */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 18, animationDelay: "250ms", opacity: 0 }}>
        <div className="panel-header">
          <div>
            <div className="panel-title">KPI Drift Monitor</div>
            <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>
              Powered by River ADWIN algorithm
            </div>
          </div>
          <span className="tag" style={{ background: "#f3f4f6", color: "#111111", borderColor: "var(--border)" }}>
            <Cpu size={11} style={{ marginRight: 4 }} /> ADWIN
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {data.kpis.map((kpi: any, i: number) => {
            const driftPct = kpi.drift_score * 100;
            const tagClass = driftPct > 40 ? "tag-danger" : driftPct > 20 ? "tag-warning" : "tag-success";
            return (
              <div key={i}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "220px 1fr auto",
                    alignItems: "center",
                    gap: 16,
                    marginBottom: 6,
                  }}
                >
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{kpi.kpi_name}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      Base: {kpi.baseline_value?.toLocaleString(undefined, { maximumFractionDigits: 1 })} →
                      Target: {kpi.target_value?.toLocaleString(undefined, { maximumFractionDigits: 1 })} {kpi.unit}
                    </div>
                  </div>
                  <div>
                    <div className="progress-track">
                      <div
                        className="progress-fill"
                        style={{ width: `${Math.min(driftPct, 100)}%`, background: "#000000" }}
                      />
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 120 }}>
                    <span
                      className="mono"
                      style={{ fontSize: 13, fontWeight: 800, color: "#000000", minWidth: 50, textAlign: "right" }}
                    >
                      {driftPct.toFixed(0)}%
                    </span>
                    <span className={`tag ${tagClass}`} style={{ fontSize: 10 }}>
                      {kpi.current_value?.toLocaleString(undefined, { maximumFractionDigits: 1 })} {kpi.unit}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* BPR Rules */}
      <div>
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 14, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>
            Business Process Rules Engine
          </div>
          <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
            Review, assess, and update active business rules
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {data.bpr_rules.map((rule: any, i: number) => (
            <div
              key={rule.id}
              className="animate-fade-up"
              style={{ animationDelay: `${400 + i * 60}ms`, opacity: 0 }}
            >
              <RuleCard rule={rule} onUpdate={handleRuleUpdate} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
