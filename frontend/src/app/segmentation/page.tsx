"use client";
import { useEffect, useState } from "react";
import { getSegments } from "@/lib/api";
import { Doughnut } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from "chart.js";
import { PieChart, Crown, AlertOctagon, Sprout, UserX } from "lucide-react";

ChartJS.register(ArcElement, Tooltip, Legend);

const SEGMENT_ICONS: any = {
  Champions:       { icon: Crown,        color: "#000000" },
  "At-Risk":       { icon: AlertOctagon, color: "#4b5563" },
  "New / Growing": { icon: Sprout,       color: "#6b7280" },
  Lost:            { icon: UserX,        color: "#9ca3af" },
};

export default function SegmentationPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { getSegments().then(setData).finally(() => setLoading(false)); }, []);

  if (loading) return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
      {[...Array(4)].map((_, i) => <div key={i} className="skeleton" style={{ height: 200, borderRadius: 16 }} />)}
    </div>
  );

  if (!data || !data.segments) return (
    <div style={{ textAlign: "center", padding: "80px 0", color: "var(--text-muted)" }}>
      No segmentation data available.
    </div>
  );

  const donutColors = ["#000000", "#374151", "#6b7280", "#9ca3af", "#d1d5db"];

  const donutData = {
    labels: data.segments.map((s: any) => s.name),
    datasets: [{
      data: data.segments.map((s: any) => s.count),
      backgroundColor: donutColors.slice(0, data.segments.length),
      borderWidth: 2,
      borderColor: "#ffffff",
      hoverOffset: 6,
    }],
  };

  const donutOptions: any = {
    plugins: {
      legend: {
        position: "bottom",
        labels: { color: "#111111", padding: 12, font: { size: 11, weight: "600" }, boxWidth: 10 },
      },
    },
    cutout: "65%",
    maintainAspectRatio: true,
  };

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div className="page-title">
          <div className="page-title-icon">
            <PieChart size={18} />
          </div>
          Customer Segmentation
        </div>
        <p className="page-subtitle">
          RFM-based K-Means clustering —
          <span style={{ color: "#000000", fontWeight: 700 }}> {data.total_customers.toLocaleString()} </span>
          customers analysed
        </p>
      </div>

      {/* Donut + Segment Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 14, marginBottom: 18 }}>
        {/* Donut chart */}
        <div
          className="chart-panel animate-fade-up"
          style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity: 0 }}
        >
          <div className="chart-title" style={{ alignSelf: "flex-start", marginBottom: 4 }}>Distribution</div>
          <div className="chart-subtitle" style={{ alignSelf: "flex-start" }}>By segment share</div>
          <div style={{ width: 210, height: 210 }}>
            <Doughnut data={donutData} options={donutOptions} />
          </div>
        </div>

        {/* Segment cards grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {data.segments.map((seg: any, idx: number) => {
            const cfg = SEGMENT_ICONS[seg.name] || { icon: PieChart, color: "#000000" };
            const Icon = cfg.icon;
            return (
              <div
                key={seg.id}
                className="panel panel-body animate-fade-up"
                style={{ animationDelay: `${idx * 70}ms`, opacity: 0, position: "relative", overflow: "hidden" }}
              >
                <div style={{
                  position: "absolute", top: 0, left: 0, right: 0, height: 3,
                  background: "#000000",
                }} />

                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: 9,
                    background: "#f3f4f6", border: "1px solid var(--border)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <Icon size={17} color="#000000" />
                  </div>
                  <div>
                    <div style={{ fontWeight: 800, fontSize: 14, color: "var(--text-primary)" }}>{seg.name}</div>
                    <div style={{ fontSize: 12, color: "#111111", fontWeight: 600 }}>
                      {seg.count.toLocaleString()} <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>customers</span>
                    </div>
                  </div>
                </div>

                <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 14, lineHeight: 1.5 }}>
                  {seg.description}
                </p>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                  {[
                    ["Recency",  `${seg.avg_recency}d`],
                    ["Orders",   seg.avg_frequency],
                    ["Avg Spend",`$${seg.avg_monetary.toLocaleString(undefined,{maximumFractionDigits:0})}`],
                  ].map(([label, val]) => (
                    <div
                      key={label}
                      style={{
                        background: "#f9fafb", border: "1px solid var(--border)",
                        borderRadius: 8, padding: "8px 6px", textAlign: "center",
                      }}
                    >
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#000000", fontVariantNumeric: "tabular-nums" }}>
                        {val}
                      </div>
                      <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 2, fontWeight: 600 }}>{label}</div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Top Customers Table */}
      <div className="panel panel-body animate-fade-up" style={{ animationDelay: "380ms", opacity: 0 }}>
        <div className="panel-header">
          <span className="panel-title">Top Customers by Revenue</span>
          <span className="tag tag-info">Top 10 shown</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Customer ID</th>
                <th>Segment</th>
                <th>Recency (days)</th>
                <th>Orders</th>
                <th>Total Spend</th>
              </tr>
            </thead>
            <tbody>
              {data.top_customers.slice(0, 10).map((c: any, i: number) => {
                return (
                  <tr key={i}>
                    <td className="td-mono td-primary">{c.customer_id}</td>
                    <td>
                      <span className="tag" style={{
                        background: "#f3f4f6", color: "#111111", borderColor: "var(--border)", fontWeight: 600,
                      }}>{c.segment}</span>
                    </td>
                    <td className="td-num" style={{ color: "var(--text-muted)" }}>{c.recency}</td>
                    <td className="td-num" style={{ color: "var(--text-muted)" }}>{c.frequency}</td>
                    <td className="td-num td-primary" style={{ fontWeight: 700, color: "#000000" }}>
                      ${c.monetary.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
