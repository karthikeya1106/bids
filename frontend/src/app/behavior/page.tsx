"use client";
import { useEffect, useState } from "react";
import { getBehavior } from "@/lib/api";
import { Bar, Doughnut } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement,
  ArcElement, Title, Tooltip, Legend,
} from "chart.js";
import { Activity, Users, RotateCcw, TrendingDown } from "lucide-react";
import dynamic from "next/dynamic";

ChartJS.register(CategoryScale, LinearScale, BarElement, ArcElement, Title, Tooltip, Legend);
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

export default function BehaviorPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { getBehavior().then(setData).finally(() => setLoading(false)); }, []);

  if (loading) return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
      {[...Array(6)].map((_, i) => <div key={i} className="skeleton" style={{ height: 200, borderRadius: 16 }} />)}
    </div>
  );

  if (!data) return (
    <div style={{ textAlign: "center", padding: "80px 0", color: "var(--text-muted)" }}>
      Failed to load behavior data.
    </div>
  );

  const metrics = [
    { label: "Total Customers", value: data.total_customers.toLocaleString(), icon: Users },
    { label: "Repeat Buyers",   value: data.repeat_customers.toLocaleString(), icon: RotateCcw },
    { label: "Retention Rate",  value: `${data.retention_rate}%`,              icon: Activity },
    { label: "Churn Rate",      value: `${data.churn_rate}%`,                  icon: TrendingDown },
  ];

  const maxFunnel = data.funnel[0]?.value || 1;

  const barData = {
    labels: data.top_products.map((p: any) => p.name),
    datasets: [{
      label: "Sales ($)",
      data: data.top_products.map((p: any) => p.sales),
      backgroundColor: "#111111",
      borderColor: "#000000",
      borderWidth: 1,
      borderRadius: 4,
    }],
  };

  const barOptions: any = {
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: "y" as const,
    plugins: { legend: { display: false } },
    scales: {
      x: {
        ticks: { color: "#6b7280", callback: (v: any) => "$" + (v / 1000).toFixed(0) + "k", font: { size: 10 } },
        grid: { color: "#f3f4f6" },
      },
      y: {
        ticks: { color: "#111111", font: { size: 11, weight: "500" } },
        grid: { display: false },
      },
    },
  };

  const clvData = {
    labels: data.clv_by_segment.map((s: any) => s.segment),
    datasets: [{
      data: data.clv_by_segment.map((s: any) => s.clv || s.sales),
      backgroundColor: ["#000000", "#4b5563", "#9ca3af"],
      borderWidth: 2,
      borderColor: "#ffffff",
    }],
  };

  const donutOptions: any = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: { color: "#111111", font: { size: 12, weight: "600" }, padding: 14 },
      },
    },
    cutout: "68%",
  };

  const heatmapTrace: any = {
    z: data.heatmap.z,
    x: ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
    y: data.heatmap.y,
    type: "heatmap",
    colorscale: [["0", "#f9fafb"], ["0.5", "#9ca3af"], ["1", "#000000"]],
    showscale: false,
  };

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div className="page-title">
          <div className="page-title-icon">
            <Activity size={18} />
          </div>
          Customer Behavior Analytics
        </div>
        <p className="page-subtitle">Purchase patterns, retention funnel, and engagement deep-dive</p>
      </div>

      {/* Metric Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 18 }}>
        {metrics.map((m, i) => {
          const Icon = m.icon;
          return (
            <div
              key={i}
              className="kpi-card animate-fade-up"
              style={{ animationDelay: `${i * 60}ms`, opacity: 0 }}
            >
              <div className="kpi-accent-bar" />
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                <span className="kpi-label">{m.label}</span>
                <div className="kpi-icon-box">
                  <Icon size={16} color="#000000" />
                </div>
              </div>
              <div className="kpi-value" style={{ fontSize: 24 }}>{m.value}</div>
            </div>
          );
        })}
      </div>

      {/* Heatmap + Funnel */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        <div className="chart-panel animate-fade-up" style={{ animationDelay: "280ms", opacity: 0 }}>
          <div className="chart-title">Purchase Heatmap</div>
          <div className="chart-subtitle">Day of week × Month activity</div>
          <div style={{ height: 200 }}>
            <Plot
              data={[heatmapTrace]}
              layout={{
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",
                margin: { t: 10, b: 30, l: 50, r: 10 },
                xaxis: { tickfont: { color: "#6b7280", size: 10 } },
                yaxis: { tickfont: { color: "#111111", size: 10 } },
                height: 190,
              }}
              config={{ displayModeBar: false }}
              style={{ width: "100%", height: "190px" }}
            />
          </div>
        </div>

        <div className="chart-panel animate-fade-up" style={{ animationDelay: "340ms", opacity: 0 }}>
          <div className="chart-title">Customer Journey Funnel</div>
          <div className="chart-subtitle">Acquisition → Purchase flow</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 4 }}>
            {data.funnel.map((stage: any, i: number) => {
              const pct = ((stage.value / maxFunnel) * 100).toFixed(0);
              return (
                <div key={i}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{stage.stage}</span>
                    <span style={{ fontSize: 12, color: "#000000", fontWeight: 700 }}>
                      {stage.value.toLocaleString()} <span style={{ color: "var(--text-muted)" }}>({pct}%)</span>
                    </span>
                  </div>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${pct}%`, background: "#000000" }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Products + CLV */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div className="chart-panel animate-fade-up" style={{ animationDelay: "400ms", opacity: 0 }}>
          <div className="chart-title">Top Sub-Categories by Revenue</div>
          <div className="chart-subtitle">Horizontal bar comparison</div>
          <div style={{ height: 230 }}>
            {data.top_products.length > 0
              ? <Bar data={barData} options={barOptions} />
              : <p style={{ fontSize: 12, color: "var(--text-muted)" }}>No data available</p>}
          </div>
        </div>

        <div className="chart-panel animate-fade-up" style={{ animationDelay: "460ms", opacity: 0 }}>
          <div className="chart-title">Customer Lifetime Value by Segment</div>
          <div className="chart-subtitle">Proportional revenue distribution</div>
          <div style={{ height: 230, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Doughnut data={clvData} options={donutOptions} />
          </div>
        </div>
      </div>
    </div>
  );
}
