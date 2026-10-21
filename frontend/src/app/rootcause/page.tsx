"use client";
import { useEffect, useState } from "react";
import { getRootCause } from "@/lib/api";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Title, Tooltip, Legend,
} from "chart.js";
import { AlertTriangle, Target, Flame } from "lucide-react";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

function FishboneArm({ branch, causes }: any) {
  return (
    <div
      className="panel panel-body animate-fade-up"
      style={{ borderLeft: `4px solid #000000`, opacity: 0 }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 7,
          background: "#000000",
          display: "flex", alignItems: "center", justifyItems: "center", justifyContent: "center",
          fontSize: 13, fontWeight: 800, color: "#ffffff",
        }}>
          {branch[0]}
        </div>
        <span style={{ fontWeight: 800, fontSize: 13, color: "#000000" }}>{branch}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {causes.map((c: any, i: number) => (
          <div
            key={i}
            style={{
              background: "#f9fafb", borderRadius: 10, padding: "10px 12px",
              border: `1px solid var(--border)`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, alignItems: "center" }}>
              <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-primary)" }}>{c.factor}</span>
              <span
                className="tag"
                style={{
                  background: "#000000", color: "#ffffff",
                  fontSize: 10, fontWeight: 700,
                }}
              >
                {(c.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div className="progress-track" style={{ marginBottom: 6 }}>
              <div className="progress-fill" style={{ width: `${c.confidence * 100}%`, background: "#000000" }} />
            </div>
            <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>{c.evidence}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function RootCausePage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { getRootCause().then(setData).finally(() => setLoading(false)); }, []);

  if (loading) return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {[...Array(3)].map((_, i) => <div key={i} className="skeleton" style={{ height: 160, borderRadius: 16 }} />)}
    </div>
  );

  if (!data) return (
    <div style={{ textAlign: "center", padding: "80px 0", color: "var(--text-muted)" }}>
      Failed to load root cause data.
    </div>
  );

  const anomalySet = new Set(data.anomalies.map((a: any) => a.date));
  const chartData = {
    labels: data.monthly_series.map((d: any) => d.date),
    datasets: [{
      label: "Monthly Sales",
      data: data.monthly_series.map((d: any) => d.value),
      borderColor: "#000000",
      backgroundColor: "rgba(0, 0, 0, 0.05)",
      fill: true, tension: 0.35,
      borderWidth: 2,
      pointRadius: (ctx: any) => anomalySet.has(data.monthly_series[ctx.dataIndex]?.date) ? 8 : 3,
      pointBackgroundColor: (ctx: any) => {
        const d = data.monthly_series[ctx.dataIndex];
        if (!d) return "#000000";
        const anomaly = data.anomalies.find((a: any) => a.date === d.date);
        if (!anomaly) return "#000000";
        return anomaly.type === "drop" ? "#dc2626" : "#d97706";
      },
      pointBorderColor: "#ffffff",
      pointBorderWidth: 1.5,
    }],
  };

  const chartOptions: any = {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          afterLabel: (ctx: any) => {
            const d = data.monthly_series[ctx.dataIndex];
            const a = data.anomalies.find((x: any) => x.date === d?.date);
            return a ? `⚠ ${a.type.toUpperCase()} (z=${a.z_score})` : "";
          },
        },
      },
    },
    scales: {
      x: { ticks: { color: "#6b7280", maxTicksLimit: 10, font: { size: 10 } }, grid: { color: "#f3f4f6" } },
      y: { ticks: { color: "#6b7280", callback: (v: any) => "$" + (v / 1000).toFixed(0) + "k", font: { size: 10 } }, grid: { color: "#f3f4f6" } },
    },
  };

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div className="page-title">
          <div className="page-title-icon">
            <AlertTriangle size={18} />
          </div>
          Root Cause Analysis
        </div>
        <p className="page-subtitle">Anomaly detection and Ishikawa fishbone causal breakdown</p>
      </div>

      {/* Primary root cause banner */}
      {data.top_root_cause?.factor && (
        <div
          className="animate-fade-up"
          style={{
            background: "#fef2f2",
            border: "1px solid #fecaca",
            borderLeft: "4px solid #dc2626",
            borderRadius: 12,
            padding: "14px 18px",
            marginBottom: 18,
            display: "flex",
            alignItems: "flex-start",
            gap: 14,
            opacity: 0,
          }}
        >
          <Flame size={20} style={{ color: "#dc2626", flexShrink: 0, marginTop: 2 }} />
          <div>
            <div style={{ fontWeight: 800, fontSize: 14, color: "#111111", marginBottom: 4 }}>
              Primary Root Cause: {data.top_root_cause.factor}
            </div>
            <div style={{ fontSize: 13, color: "#374151", marginBottom: 8, lineHeight: 1.5 }}>
              {data.top_root_cause.evidence}
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <span className="tag tag-danger">
                {(data.top_root_cause.confidence * 100).toFixed(0)}% confidence
              </span>
              <span className="tag tag-warning">{data.top_root_cause.branch} branch</span>
            </div>
          </div>
        </div>
      )}

      {/* Sales timeline */}
      <div className="chart-panel animate-fade-up" style={{ marginBottom: 14, animationDelay: "100ms", opacity: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
          <div>
            <div className="chart-title">Sales Timeline with Anomaly Detection</div>
            <div className="chart-subtitle">
              <span style={{ color: "#dc2626", fontWeight: 700 }}>● Drop</span>
              <span style={{ marginLeft: 12, color: "#d97706", fontWeight: 700 }}>● Spike</span>
              <span style={{ marginLeft: 16, color: "var(--text-muted)", fontWeight: 500 }}>
                {data.anomalies.length} anomalies flagged
              </span>
            </div>
          </div>
        </div>
        <div style={{ height: 240 }}>
          {data.monthly_series.length > 0
            ? <Line data={chartData} options={chartOptions} />
            : <p style={{ fontSize: 12, color: "var(--text-muted)", paddingTop: 16 }}>Seed the database to view analysis.</p>}
        </div>
      </div>

      {/* Anomalies grid */}
      {data.anomalies.length > 0 && (
        <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, animationDelay: "200ms", opacity: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Detected Anomalies</span>
            <span className="tag tag-danger">{data.anomalies.length} events</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
            {data.anomalies.map((a: any, i: number) => {
              const isDrop = a.type === "drop";
              return (
                <div
                  key={i}
                  style={{
                    background: isDrop ? "#fef2f2" : "#fffbeb",
                    border: `1px solid ${isDrop ? "#fecaca" : "#fde68a"}`,
                    borderRadius: 10, padding: "10px 12px",
                  }}
                >
                  <div style={{ fontWeight: 800, fontSize: 12, color: isDrop ? "#dc2626" : "#d97706", marginBottom: 4 }}>
                    {a.date} — {a.type.toUpperCase()}
                  </div>
                  <div style={{ fontSize: 11.5, color: "#374151", fontWeight: 500 }}>
                    Sales: ${a.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>z-score: {a.z_score}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Fishbone */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>
          Ishikawa Fishbone — Causal Analysis
        </div>
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 14 }}>
          Causal factor scoring across 4 branches
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {Object.entries(data.fishbone || {}).map(([branch, causes]: any) => (
          <FishboneArm
            key={branch}
            branch={branch}
            causes={causes}
          />
        ))}
      </div>
    </div>
  );
}
