"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Doughnut } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip, Legend, type ChartOptions } from "chart.js";
import {
  AlertOctagon, AlertTriangle, ArrowRight, Crown, PieChart,
  RefreshCw, Sprout, UserX,
} from "lucide-react";
import { getSegments } from "@/lib/api";
import AdaptiveModule, { type AdaptiveModulePayload } from "@/components/AdaptiveModule";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";

ChartJS.register(ArcElement, Tooltip, Legend);

interface Segment {
  name: string;
  color: string;
  description: string;
  count: number;
  share: number;
  revenue: number;
  revenue_share: number;
  avg_monetary: number;
  avg_frequency: number;
  avg_recency: number;
  avg_order_value: number;
  avg_quantity: number;
  avg_discount: number;
  inactive_share: number;
  top_category: string;
  top_region: string;
}

interface Customer {
  customer_id: string;
  customer_name: string | null;
  account_segment: string;
  region: string;
  segment: string;
  recency: number;
  frequency: number;
  monetary: number;
  avg_order_value: number;
  top_category: string;
}

interface SegmentData {
  has_data: boolean;
  segments: Segment[];
  top_customers: Customer[];
  total_customers: number;
  total_revenue: number;
  averages: { recency: number; frequency: number; monetary: number; order_value: number };
}

const SEGMENT_ICONS: Record<string, typeof Crown> = {
  Champions: Crown,
  "New / Growing": Sprout,
  "At-Risk": AlertOctagon,
  Lost: UserX,
};

export default function SegmentationPage() {
  const [data, setData] = useState<SegmentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getSegments()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError("");
      })
      .catch(() => {
        if (!cancelled) setError("Could not load segmentation. Make sure the FastAPI server is running on port 8000.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [reloadKey]);

  const refresh = () => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  };

  const adaptive = data && (data as { mode?: string }).mode === "adaptive"
    ? (data as unknown as AdaptiveModulePayload)
    : null;

  const header = (
    <div className="page-header" style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="page-title">
            <div className="page-title-icon"><PieChart size={18} /></div>
            Customer Segments
          </div>
          <p className="page-subtitle">
            {adaptive
              ? "K-Means segments built from the dataset's own numeric features, profiled against the observed outcome."
              : "Quintile RFM scores clustered with K-Means, then ranked into four business segments."}
          </p>
        </div>
        <button className="btn-ghost" onClick={refresh} style={{ fontSize: 12 }}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>
    </div>
  );

  if (loading && !data) {
    return (
      <div>
        {header}
        <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 14, marginBottom: 16 }}>
          <div className="skeleton" style={{ height: 300 }} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {[...Array(4)].map((_, i) => <div key={i} className="skeleton" style={{ height: 144 }} />)}
          </div>
        </div>
        <div className="skeleton" style={{ height: 260 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "64px 24px" }}>
          <AlertTriangle size={30} color="#b91c1c" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>Segmentation unavailable</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 440, margin: "0 auto 18px" }}>{error}</p>
          <button className="btn-primary" onClick={refresh}><RefreshCw size={14} /> Try again</button>
        </div>
      </div>
    );
  }

  if (adaptive) {
    return (
      <div>
        {header}
        <AdaptiveModule payload={adaptive} onRefresh={refresh} />
      </div>
    );
  }

  if (!data?.has_data || data.segments.length === 0) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "72px 24px" }}>
          <PieChart size={28} color="#111111" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 6 }}>No customers to segment</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 420, margin: "0 auto 20px" }}>
            Segmentation needs order history per customer. Upload a dataset to build RFM profiles.
          </p>
          <Link href="/upload" className="btn-primary">Upload data <ArrowRight size={14} /></Link>
        </div>
      </div>
    );
  }

  const { segments, top_customers, total_customers, total_revenue, averages } = data;
  const atRisk = segments.find((s) => s.name === "At-Risk");
  const lost = segments.find((s) => s.name === "Lost");
  const champions = segments.find((s) => s.name === "Champions");

  const donutData = {
    labels: segments.map((s) => s.name),
    datasets: [{
      data: segments.map((s) => s.count),
      backgroundColor: segments.map((s) => s.color),
      borderColor: "#ffffff",
      borderWidth: 3,
      hoverOffset: 6,
    }],
  };

  const donutOptions: ChartOptions<"doughnut"> = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: "68%",
    plugins: {
      legend: {
        position: "bottom",
        labels: {
          color: "#111111", padding: 12, boxWidth: 9, boxHeight: 9,
          font: { size: 11, weight: 600 }, usePointStyle: true,
        },
      },
      tooltip: {
        backgroundColor: "#000000",
        padding: 10,
        callbacks: {
          label: (ctx) => {
            const segment = segments[ctx.dataIndex];
            return ` ${segment.name}: ${formatNumber(segment.count)} customers (${formatPercent(segment.share)})`;
          },
        },
      },
    },
  };

  return (
    <div>
      {header}

      {/* Overview strip */}
      <div
        className="panel"
        style={{
          display: "flex", flexWrap: "wrap", gap: 24, padding: "12px 18px", marginBottom: 14,
          fontSize: 11.5, color: "var(--text-secondary)",
        }}
      >
        <span><strong style={{ color: "#111111" }}>{formatNumber(total_customers)}</strong> customers segmented</span>
        <span><strong style={{ color: "#111111" }}>{formatCurrency(total_revenue)}</strong> lifetime revenue</span>
        <span><strong style={{ color: "#111111" }}>{formatPercent(champions?.revenue_share ?? 0)}</strong> of revenue from Champions</span>
        <span style={{ marginLeft: "auto" }}>
          Avg {formatCurrency(averages.monetary)} spend · {averages.frequency.toFixed(1)} orders · {averages.recency} days since last order
        </span>
      </div>

      {/* Donut + cards */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 14 }}>
        <div
          className="panel panel-body animate-fade-up"
          style={{ flex: "0 1 300px", minWidth: 260, opacity: 0, display: "flex", flexDirection: "column" }}
        >
          <div className="panel-header">
            <span className="panel-title">Customer distribution</span>
          </div>
          <div style={{ height: 220, marginBottom: 10 }}>
            <Doughnut data={donutData} options={donutOptions} />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 9, borderTop: "1px solid var(--border-subtle)", paddingTop: 12 }}>
            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-muted)" }}>
              Revenue share
            </div>
            {segments.map((segment) => (
              <div key={segment.name}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
                  <span style={{ fontWeight: 600 }}>{segment.name}</span>
                  <span style={{ color: "var(--text-muted)" }}>{formatPercent(segment.revenue_share)}</span>
                </div>
                <div className="progress-track" style={{ height: 4 }}>
                  <div className="progress-fill" style={{ width: `${segment.revenue_share}%`, background: segment.color }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: "1 1 560px", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 12 }}>
          {segments.map((segment, index) => {
            const Icon = SEGMENT_ICONS[segment.name] ?? PieChart;
            return (
              <div
                key={segment.name}
                className="panel panel-body animate-fade-up"
                style={{ position: "relative", overflow: "hidden", opacity: 0, animationDelay: `${index * 60}ms` }}
              >
                <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, background: segment.color }} />

                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: 9, background: "#f3f4f6",
                    border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <Icon size={17} color="#000000" />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 800, fontSize: 14 }}>{segment.name}</div>
                    <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                      {formatNumber(segment.count)} customers · {formatPercent(segment.share)}
                    </div>
                  </div>
                  <span className="tag tag-info">{formatPercent(segment.revenue_share)} rev</span>
                </div>

                <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.55, marginBottom: 12, minHeight: 36 }}>
                  {segment.description}
                </p>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6, marginBottom: 10 }}>
                  {[
                    ["Avg spend", formatCurrency(segment.avg_monetary)],
                    ["Orders", segment.avg_frequency.toFixed(1)],
                    ["Recency", `${Math.round(segment.avg_recency)}d`],
                    ["AOV", formatCurrency(segment.avg_order_value)],
                  ].map(([label, value]) => (
                    <div key={label} style={{
                      background: "#f9fafb", border: "1px solid var(--border)",
                      borderRadius: 7, padding: "6px 4px", textAlign: "center",
                    }}>
                      <div style={{ fontSize: 11, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{value}</div>
                      <div style={{ fontSize: 8.5, color: "var(--text-muted)", fontWeight: 700, letterSpacing: "0.03em", textTransform: "uppercase" }}>
                        {label}
                      </div>
                    </div>
                  ))}
                </div>

                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 9 }}>
                  <span className="tag" style={{ background: "#f3f4f6", borderColor: "var(--border)", color: "#111111" }}>
                    {segment.top_category}
                  </span>
                  <span className="tag" style={{ background: "#f3f4f6", borderColor: "var(--border)", color: "#111111" }}>
                    {segment.top_region}
                  </span>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 9.5, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap" }}>
                    Inactive 180d+
                  </span>
                  <div className="progress-track" style={{ height: 4, flex: 1 }}>
                    <div
                      className="progress-fill"
                      style={{ width: `${segment.inactive_share}%`, background: segment.inactive_share > 60 ? "#9ca3af" : "#111111" }}
                    />
                  </div>
                  <span style={{ fontSize: 10.5, fontWeight: 700 }}>{formatPercent(segment.inactive_share)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Comparison table */}
      <div className="panel animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div className="panel-body" style={{ paddingBottom: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Segment comparison</span>
            <span className="tag tag-info">RFM + K-Means</span>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Segment</th>
                <th style={{ textAlign: "right" }}>Customers</th>
                <th style={{ textAlign: "right" }}>Share</th>
                <th style={{ textAlign: "right" }}>Revenue</th>
                <th style={{ textAlign: "right" }}>Rev. share</th>
                <th style={{ textAlign: "right" }}>Avg spend</th>
                <th style={{ textAlign: "right" }}>Orders</th>
                <th style={{ textAlign: "right" }}>Recency</th>
                <th style={{ textAlign: "right" }}>AOV</th>
              </tr>
            </thead>
            <tbody>
              {segments.map((segment) => (
                <tr key={segment.name}>
                  <td className="td-primary">
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: segment.color }} />
                      {segment.name}
                    </span>
                  </td>
                  <td className="td-num" style={{ textAlign: "right" }}>{formatNumber(segment.count)}</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{formatPercent(segment.share)}</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(segment.revenue)}</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{formatPercent(segment.revenue_share)}</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(segment.avg_monetary)}</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{segment.avg_frequency.toFixed(1)}</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{Math.round(segment.avg_recency)}d</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(segment.avg_order_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ padding: "10px 16px", fontSize: 10.5, color: "var(--text-muted)", borderTop: "1px solid var(--border-subtle)" }}>
          Champions spend the most and bought recently. At-Risk customers still carry meaningful revenue but
          have not ordered in {Math.round(atRisk?.avg_recency ?? 0)} days on average.
        </div>
      </div>

      {/* Top customers */}
      <div className="panel animate-fade-up" style={{ opacity: 0 }}>
        <div className="panel-body" style={{ paddingBottom: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Highest-value customers</span>
            <span className="tag tag-info">Top 15 by lifetime spend</span>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table" style={{ minWidth: 720 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Customer</th>
                <th>Segment</th>
                <th>Account type</th>
                <th style={{ textAlign: "right" }}>Recency</th>
                <th style={{ textAlign: "right" }}>Orders</th>
                <th style={{ textAlign: "right" }}>Lifetime spend</th>
                <th style={{ textAlign: "right" }}>Avg order</th>
              </tr>
            </thead>
            <tbody>
              {top_customers.map((customer, index) => (
                <tr key={customer.customer_id}>
                  <td style={{ color: "var(--text-muted)", fontSize: 11 }}>{index + 1}</td>
                  <td className="td-primary">
                    <div>{customer.customer_name || customer.customer_id}</div>
                    <div className="mono" style={{ fontSize: 10, color: "var(--text-muted)", fontWeight: 400 }}>
                      {customer.customer_id}
                    </div>
                  </td>
                  <td>
                    <span className="tag" style={{
                      background: segments.find((s) => s.name === customer.segment)?.color ?? "#111111",
                      color: "#ffffff", borderColor: "transparent",
                    }}>
                      {customer.segment}
                    </span>
                  </td>
                  <td style={{ fontSize: 11.5 }}>{customer.account_segment}</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{customer.recency}d</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{customer.frequency}</td>
                  <td className="td-num" style={{ textAlign: "right", fontWeight: 700, color: "#000000" }}>
                    {formatCurrency(customer.monetary)}
                  </td>
                  <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(customer.avg_order_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ padding: "10px 16px", fontSize: 10.5, color: "var(--text-muted)", borderTop: "1px solid var(--border-subtle)" }}>
          {lost ? `${formatNumber(lost.count)} customers are classified as Lost (${formatPercent(lost.share)} of the base, ${formatPercent(lost.revenue_share)} of revenue).` : "Segments computed from the full order history."}
        </div>
      </div>
    </div>
  );
}
