"use client";
import { useEffect, useState } from "react";
import { getDashboard } from "@/lib/api";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Title, Tooltip, Legend, Filler,
} from "chart.js";
import { DollarSign, ShoppingCart, Users, TrendingUp, AlertTriangle, Info, LayoutDashboard } from "lucide-react";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

interface DashboardData {
  kpis: { total_sales: number; total_profit: number; total_orders: number; total_customers: number; avg_order_value: number; profit_margin: number };
  revenue_trend: { month: string; sales: number; profit: number }[];
  category_breakdown: { category: string; sales: number }[];
  alerts: { type: string; message: string; severity: string }[];
}

const KPI_CONFIG = [
  { key: "total_sales",     label: "Total Revenue",    icon: DollarSign,   prefix: "$", sub: "Cumulative sales" },
  { key: "total_profit",    label: "Net Profit",       icon: TrendingUp,   prefix: "$", sub: "After all costs" },
  { key: "total_orders",    label: "Total Orders",     icon: ShoppingCart, prefix: "",  sub: "Unique transactions" },
  { key: "total_customers", label: "Customers",        icon: Users,        prefix: "",  sub: "Unique customers" },
  { key: "avg_order_value", label: "Avg Order Value",  icon: DollarSign,   prefix: "$", sub: "Per transaction" },
  { key: "profit_margin",   label: "Profit Margin",    icon: TrendingUp,   prefix: "",  suffix: "%", sub: "Overall margin" },
];

function KPICard({ cfg, value, delay }: { cfg: typeof KPI_CONFIG[0]; value: number; delay: number }) {
  const Icon = cfg.icon;
  const formatted = typeof value === "number"
    ? value.toLocaleString(undefined, { maximumFractionDigits: 1 })
    : value;
  return (
    <div
      className="kpi-card animate-fade-up"
      style={{ animationDelay: `${delay}ms`, opacity: 0 }}
    >
      <div className="kpi-accent-bar" />
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 12 }}>
        <span className="kpi-label">{cfg.label}</span>
        <div className="kpi-icon-box">
          <Icon size={16} color="#000000" />
        </div>
      </div>
      <div className="kpi-value animate-count">
        {cfg.prefix}{formatted}{cfg.suffix ?? ""}
      </div>
      <div className="kpi-sub">{cfg.sub}</div>
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { getDashboard().then(setData).finally(() => setLoading(false)); }, []);

  if (loading) return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, marginBottom: 20 }}>
        {[...Array(6)].map((_, i) => <div key={i} className="skeleton" style={{ height: 110 }} />)}
      </div>
      <div className="skeleton" style={{ height: 280, marginBottom: 16 }} />
      <div className="skeleton" style={{ height: 160 }} />
    </div>
  );

  if (!data) return (
    <div style={{ textAlign: "center", padding: "80px 0", color: "var(--text-muted)" }}>
      Backend offline — start the FastAPI server and refresh.
    </div>
  );

  const chartData = {
    labels: data.revenue_trend.map(r => r.month),
    datasets: [
      {
        label: "Revenue",
        data: data.revenue_trend.map(r => r.sales),
        borderColor: "#000000",
        backgroundColor: "rgba(0, 0, 0, 0.05)",
        fill: true,
        tension: 0.35,
        pointRadius: 3,
        pointHoverRadius: 6,
        borderWidth: 2.5,
      },
      {
        label: "Profit",
        data: data.revenue_trend.map(r => r.profit),
        borderColor: "#4b5563",
        backgroundColor: "rgba(75, 85, 99, 0.04)",
        fill: true,
        tension: 0.35,
        pointRadius: 3,
        pointHoverRadius: 6,
        borderWidth: 2,
        borderDash: [4, 4],
      },
    ],
  };

  const chartOptions: any = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: {
          color: "#111111",
          boxWidth: 12,
          padding: 16,
          font: { size: 12, weight: "600" },
        },
      },
    },
    scales: {
      x: {
        ticks: { color: "#6b7280", maxTicksLimit: 10, font: { size: 11 } },
        grid: { color: "#f3f4f6" },
      },
      y: {
        ticks: {
          color: "#6b7280",
          callback: (v: any) => "$" + (v / 1000).toFixed(0) + "k",
          font: { size: 11 },
        },
        grid: { color: "#f3f4f6" },
      },
    },
  };

  const total = data.category_breakdown.reduce((s, c) => s + c.sales, 0);

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div className="page-title">
          <div className="page-title-icon">
            <LayoutDashboard size={18} />
          </div>
          Executive Dashboard
        </div>
        <p className="page-subtitle">Real-time KPI overview and business performance at a glance</p>
      </div>

      {/* KPI Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, marginBottom: 20 }}>
        {KPI_CONFIG.map((cfg, i) => (
          <KPICard
            key={cfg.key}
            cfg={cfg}
            value={(data.kpis as any)[cfg.key]}
            delay={i * 55}
          />
        ))}
      </div>

      {/* Chart + Alerts */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 14, marginBottom: 14 }}>
        {/* Revenue Chart */}
        <div className="chart-panel animate-fade-up" style={{ animationDelay: "350ms", opacity: 0 }}>
          <div className="chart-title">Revenue & Profit Trend</div>
          <div className="chart-subtitle">Monthly performance over time</div>
          <div style={{ height: 260 }}>
            <Line data={chartData} options={chartOptions} />
          </div>
        </div>

        {/* Alerts */}
        <div className="panel panel-body animate-fade-up" style={{ animationDelay: "400ms", opacity: 0 }}>
          <div
            style={{
              display: "flex", alignItems: "center", gap: 7,
              marginBottom: 14, fontWeight: 700, fontSize: 13, color: "var(--text-primary)",
            }}
          >
            <AlertTriangle size={15} color="#000000" />
            System Alerts
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.alerts.length === 0 && (
              <p style={{ fontSize: 12, color: "var(--text-muted)" }}>No active alerts</p>
            )}
            {data.alerts.map((a, i) => (
              <div
                key={i}
                className={`alert-item alert-${a.severity === "danger" ? "danger" : a.severity === "warning" ? "warning" : "info"}`}
              >
                <Info size={14} style={{
                  color: a.severity === "danger" ? "#dc2626" : a.severity === "warning" ? "#d97706" : "#111111",
                  flexShrink: 0, marginTop: 2,
                }} />
                <p style={{ fontSize: 12, color: "var(--text-primary)", lineHeight: 1.5, fontWeight: 500 }}>{a.message}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Category Breakdown */}
      <div className="panel panel-body animate-fade-up" style={{ animationDelay: "450ms", opacity: 0 }}>
        <div className="panel-header">
          <span className="panel-title">Sales by Category</span>
          <span className="tag tag-info">{data.category_breakdown.length} categories</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {data.category_breakdown.map((cat, i) => {
            const pct = (cat.sales / total * 100).toFixed(1);
            return (
              <div key={i}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{cat.category}</span>
                  <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <span style={{ fontSize: 12, color: "#000000", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
                      {pct}%
                    </span>
                    <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 500 }}>
                      ${cat.sales.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </span>
                  </div>
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
  );
}
