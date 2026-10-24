"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Bar } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, Tooltip, Legend, type ChartOptions,
} from "chart.js";
import {
  Activity, AlertTriangle, ArrowRight, CalendarClock, Clock3, DollarSign,
  Percent, RefreshCw, Repeat, ShoppingCart, Truck, Users,
} from "lucide-react";
import { getBehavior } from "@/lib/api";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend);

interface Summary {
  customers: number;
  orders: number;
  revenue: number;
  repeat_customers: number;
  loyal_customers: number;
  champion_customers: number;
  repeat_rate: number;
  loyal_rate: number;
  retention_rate: number;
  churn_rate: number;
  new_customers_90d: number;
  retained_customers_90d: number;
  avg_orders_per_customer: number;
  avg_days_between_orders: number | null;
  avg_basket_value: number;
  avg_items_per_order: number;
  avg_ship_lag_days: number | null;
  weekend_share: number;
  avg_discount: number;
}

interface BehaviorData {
  has_data: boolean;
  summary: Summary;
  heatmap: { x: string[]; y: string[]; z: number[][]; metric: string };
  weekday_split: { day: string; sales: number; orders: number; share: number; weekend: boolean }[];
  funnel: { stage: string; value: number; pct_of_total: number; conversion: number }[];
  cohorts: { periods: number[]; rows: { cohort: string; size: number; values: (number | null)[] }[] };
  frequency_distribution: { bucket: string; customers: number; share: number }[];
  discount_bands: { band: string; orders: number; sales: number; profit: number; margin: number; share: number }[];
  segment_behavior: {
    segment: string; customers: number; orders: number; revenue: number; profit: number;
    revenue_share: number; avg_order_value: number; avg_orders_per_customer: number; margin: number;
  }[];
  top_products: { name: string; sales: number; profit: number; orders: number }[];
  top_subcategories: { name: string; sales: number; profit: number; orders: number }[];
  region_behavior: { region: string; revenue: number; orders: number; customers: number; share: number }[];
  generated_at: string;
}

function MetricCard({
  label, value, sub, icon: Icon, index,
}: { label: string; value: string; sub: string; icon: typeof Users; index: number }) {
  return (
    <div className="kpi-card animate-fade-up" style={{ animationDelay: `${index * 50}ms`, opacity: 0 }}>
      <div className="kpi-accent-bar" />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <span className="kpi-label" style={{ marginBottom: 0 }}>{label}</span>
        <div className="kpi-icon-box" style={{ width: 30, height: 30 }}><Icon size={14} color="#000000" /></div>
      </div>
      <div className="kpi-value" style={{ fontSize: 24 }}>{value}</div>
      <div className="kpi-sub">{sub}</div>
    </div>
  );
}

function shade(value: number | null, max: number): { background: string; color: string } {
  if (value === null) return { background: "#f9fafb", color: "#9ca3af" };
  const ratio = max > 0 ? Math.min(value / max, 1) : 0;
  const alpha = 0.06 + ratio * 0.9;
  return {
    background: `rgba(0, 0, 0, ${alpha.toFixed(3)})`,
    color: ratio > 0.55 ? "#ffffff" : "#111111",
  };
}

function cohortShade(value: number | null): { background: string; color: string } {
  if (value === null) return { background: "#ffffff", color: "#d1d5db" };
  const alpha = 0.05 + (value / 100) * 0.85;
  return { background: `rgba(0, 0, 0, ${alpha.toFixed(3)})`, color: value > 50 ? "#ffffff" : "#111111" };
}

export default function BehaviorPage() {
  const [data, setData] = useState<BehaviorData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getBehavior()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError("");
      })
      .catch(() => {
        if (!cancelled) setError("Could not load behavior analytics. Check that the FastAPI server is running on port 8000.");
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

  const header = (
    <div className="page-header" style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="page-title">
            <div className="page-title-icon"><Activity size={18} /></div>
            Behavior Analytics
          </div>
          <p className="page-subtitle">Purchase cadence, retention cohorts, discount sensitivity and lifecycle depth.</p>
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
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 14, marginBottom: 16 }}>
          {[...Array(6)].map((_, i) => <div key={i} className="skeleton" style={{ height: 112 }} />)}
        </div>
        <div className="skeleton" style={{ height: 280, marginBottom: 14 }} />
        <div className="skeleton" style={{ height: 300 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "64px 24px" }}>
          <AlertTriangle size={30} color="#b91c1c" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>Behavior data unavailable</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 440, margin: "0 auto 18px" }}>{error}</p>
          <button className="btn-primary" onClick={refresh}><RefreshCw size={14} /> Try again</button>
        </div>
      </div>
    );
  }

  if (!data?.has_data) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "72px 24px" }}>
          <Users size={28} color="#111111" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 6 }}>No customer history yet</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 420, margin: "0 auto 20px" }}>
            Behavior analytics needs order-level history. Upload a dataset and this page fills itself in.
          </p>
          <Link href="/upload" className="btn-primary">Upload data <ArrowRight size={14} /></Link>
        </div>
      </div>
    );
  }

  const { summary, heatmap, weekday_split, funnel, cohorts, frequency_distribution, discount_bands, segment_behavior, top_products, region_behavior } = data;
  const heatMax = Math.max(...heatmap.z.flat(), 1);
  const maxFrequency = Math.max(...frequency_distribution.map((f) => f.customers), 1);
  const worstDiscount = discount_bands.reduce<typeof discount_bands[number] | null>(
    (worst, band) => (band.margin < 0 && (!worst || band.margin < worst.margin) ? band : worst),
    null,
  );

  const weekdayChart = {
    labels: weekday_split.map((d) => d.day),
    datasets: [{
      label: "Revenue",
      data: weekday_split.map((d) => d.sales),
      backgroundColor: weekday_split.map((d) => (d.weekend ? "#9ca3af" : "#111111")),
      borderRadius: 5,
      barPercentage: 0.7,
      categoryPercentage: 0.8,
    }],
  };

  const weekdayOptions: ChartOptions<"bar"> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: "#000000",
        padding: 10,
        callbacks: {
          label: (ctx) => ` ${formatCurrency(ctx.parsed.y)}`,
          afterLabel: (ctx) => `${weekday_split[ctx.dataIndex]?.orders ?? 0} orders`,
        },
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: "#4b5563", font: { size: 11, weight: 600 } } },
      y: {
        grid: { color: "#f3f4f6" },
        ticks: {
          color: "#6b7280", font: { size: 10 },
          callback: (value) => `$${Math.round(Number(value) / 1000)}k`,
        },
      },
    },
  };

  return (
    <div>
      {header}

      {/* Metric cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 14, marginBottom: 14 }}>
        <MetricCard
          index={0}
          label="Active customers"
          value={formatNumber(summary.customers)}
          sub={`${formatNumber(summary.new_customers_90d)} acquired in last 90 days`}
          icon={Users}
        />
        <MetricCard
          index={1}
          label="Repeat purchase rate"
          value={formatPercent(summary.repeat_rate)}
          sub={`${formatNumber(summary.repeat_customers)} repeat · ${formatNumber(summary.champion_customers)} champions`}
          icon={Repeat}
        />
        <MetricCard
          index={2}
          label="90-day retention"
          value={formatPercent(summary.retention_rate)}
          sub={`${formatNumber(summary.retained_customers_90d)} retained · ${formatPercent(summary.churn_rate)} churn`}
          icon={Activity}
        />
        <MetricCard
          index={3}
          label="Orders per customer"
          value={summary.avg_orders_per_customer.toFixed(2)}
          sub={`${formatNumber(summary.orders)} orders analysed`}
          icon={ShoppingCart}
        />
        <MetricCard
          index={4}
          label="Avg days between orders"
          value={summary.avg_days_between_orders !== null ? `${summary.avg_days_between_orders}` : "—"}
          sub="Across customers with 2+ orders"
          icon={CalendarClock}
        />
        <MetricCard
          index={5}
          label="Average basket"
          value={formatCurrency(summary.avg_basket_value)}
          sub={`${summary.avg_items_per_order.toFixed(1)} items per order`}
          icon={DollarSign}
        />
      </div>

      {/* Secondary metrics strip */}
      <div
        className="panel"
        style={{
          display: "flex", flexWrap: "wrap", gap: 22, padding: "12px 18px", marginBottom: 14,
          fontSize: 11.5, color: "var(--text-secondary)",
        }}
      >
        <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <Percent size={13} /> Avg discount <strong style={{ color: "#111111" }}>{formatPercent(summary.avg_discount)}</strong>
        </span>
        <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <Clock3 size={13} /> Weekend share <strong style={{ color: "#111111" }}>{formatPercent(summary.weekend_share)}</strong>
        </span>
        <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <Truck size={13} /> Avg ship lag{" "}
          <strong style={{ color: "#111111" }}>
            {summary.avg_ship_lag_days !== null ? `${summary.avg_ship_lag_days} days` : "—"}
          </strong>
        </span>
        <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>
          {formatCurrency(summary.revenue)} lifetime revenue
        </span>
      </div>

      {/* Funnel + weekday */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 14 }}>
        <div className="panel panel-body animate-fade-up" style={{ flex: "1 1 420px", minWidth: 0, opacity: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Lifecycle funnel</span>
            <span className="tag tag-info">{formatPercent(summary.loyal_rate)} reach loyal</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
            {funnel.map((stage, index) => (
              <div key={stage.stage}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 5, gap: 8 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 600 }}>{stage.stage}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
                      {formatNumber(stage.value)}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{formatPercent(stage.pct_of_total)}</span>
                  </div>
                </div>
                <div className="progress-track" style={{ height: 7 }}>
                  <div
                    className="progress-fill"
                    style={{ width: `${stage.pct_of_total}%`, background: index === 0 ? "#000000" : `rgba(0,0,0,${1 - index * 0.18})` }}
                  />
                </div>
                {index > 0 && (
                  <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 4 }}>
                    {formatPercent(stage.conversion)} convert from previous stage
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="chart-panel animate-fade-up" style={{ flex: "1 1 420px", minWidth: 0, opacity: 0 }}>
          <div className="chart-title">Revenue by weekday</div>
          <div className="chart-subtitle">Grey bars mark weekends · revenue in USD</div>
          <div style={{ height: 220 }}>
            <Bar data={weekdayChart} options={weekdayOptions} />
          </div>
        </div>
      </div>

      {/* Heatmap */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div className="panel-header">
          <span className="panel-title">Purchase intensity heatmap</span>
          <span className="tag tag-info">Weekday × month · {heatmap.metric}</span>
        </div>

        <div style={{ overflowX: "auto" }}>
          <div style={{ minWidth: 620 }}>
            <div style={{ display: "grid", gridTemplateColumns: "44px repeat(12, 1fr)", gap: 3, marginBottom: 3 }}>
              <div />
              {heatmap.x.map((month) => (
                <div key={month} style={{ fontSize: 9.5, textAlign: "center", color: "var(--text-muted)", fontWeight: 700 }}>
                  {month}
                </div>
              ))}
            </div>
            {heatmap.y.map((day, rowIndex) => (
              <div key={day} style={{ display: "grid", gridTemplateColumns: "44px repeat(12, 1fr)", gap: 3, marginBottom: 3 }}>
                <div style={{ fontSize: 10.5, color: "var(--text-secondary)", fontWeight: 700, display: "flex", alignItems: "center" }}>
                  {day}
                </div>
                {heatmap.z[rowIndex].map((value, colIndex) => {
                  const style = shade(value, heatMax);
                  return (
                    <div
                      key={`${day}-${heatmap.x[colIndex]}`}
                      title={`${day} · ${heatmap.x[colIndex]}: ${formatCurrency(value)}`}
                      style={{
                        height: 27, borderRadius: 5, background: style.background,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 9.5, color: style.color, fontWeight: 600,
                      }}
                    >
                      {value > 0 ? `$${Math.round(value / 1000)}k` : ""}
                    </div>
                  );
                })}
              </div>
            ))}
            <div style={{ display: "flex", alignItems: "center", gap: 7, marginTop: 10, fontSize: 10, color: "var(--text-muted)" }}>
              <span>Low</span>
              {[0.08, 0.25, 0.45, 0.65, 0.9].map((alpha) => (
                <span key={alpha} style={{ width: 22, height: 9, borderRadius: 3, background: `rgba(0,0,0,${alpha})` }} />
              ))}
              <span>High</span>
            </div>
          </div>
        </div>
      </div>

      {/* Cohort retention */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div className="panel-header">
          <span className="panel-title">Acquisition cohorts &amp; retention</span>
          <span className="tag tag-info">Quarterly cohorts · % active</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table" style={{ minWidth: 700 }}>
            <thead>
              <tr>
                <th>Cohort</th>
                <th style={{ textAlign: "right" }}>Customers</th>
                {cohorts.periods.map((p) => <th key={p} style={{ textAlign: "center", minWidth: 44 }}>Q+{p}</th>)}
              </tr>
            </thead>
            <tbody>
              {cohorts.rows.map((row) => (
                <tr key={row.cohort}>
                  <td className="td-primary" style={{ whiteSpace: "nowrap" }}>{row.cohort}</td>
                  <td className="td-num" style={{ textAlign: "right" }}>{formatNumber(row.size)}</td>
                  {row.values.map((value, index) => {
                    const style = cohortShade(value);
                    return (
                      <td key={index} style={{ padding: 4 }}>
                        <div
                          title={`${row.cohort} · quarter +${index}: ${value === null ? "no data yet" : formatPercent(value)}`}
                          style={{
                            borderRadius: 5, background: style.background, color: style.color,
                            textAlign: "center", fontSize: 10.5, fontWeight: 700,
                            padding: "5px 3px", minWidth: 38,
                          }}
                        >
                          {value === null ? "—" : `${Math.round(value)}%`}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 10 }}>
          Each row is the set of customers whose first order fell in that quarter. A cell is the share of
          that cohort that ordered again N quarters later; empty cells have no history yet.
        </div>
      </div>

      {/* Frequency + discount */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 14 }}>
        <div className="panel panel-body animate-fade-up" style={{ flex: "1 1 340px", minWidth: 0, opacity: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Purchase frequency</span>
            <span className="tag tag-info">{formatNumber(summary.customers)} customers</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {frequency_distribution.map((row) => (
              <div key={row.bucket}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3, fontSize: 11.5 }}>
                  <span style={{ fontWeight: 600 }}>{row.bucket}</span>
                  <span style={{ color: "var(--text-muted)" }}>{formatNumber(row.customers)} · {formatPercent(row.share)}</span>
                </div>
                <div className="progress-track" style={{ height: 6 }}>
                  <div className="progress-fill" style={{ width: `${(row.customers / maxFrequency) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel panel-body animate-fade-up" style={{ flex: "1 1 460px", minWidth: 0, opacity: 0 }}>
          <div className="panel-header">
            <span className="panel-title">Discount bands</span>
            <span className="tag tag-warning">Margin sensitivity</span>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Discount</th>
                  <th style={{ textAlign: "right" }}>Orders</th>
                  <th style={{ textAlign: "right" }}>Revenue</th>
                  <th style={{ textAlign: "right" }}>Margin</th>
                </tr>
              </thead>
              <tbody>
                {discount_bands.map((band) => (
                  <tr key={band.band}>
                    <td className="td-primary">{band.band}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatNumber(band.orders)}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(band.sales)}</td>
                    <td style={{ textAlign: "right" }}>
                      <span className={`tag ${band.margin < 0 ? "tag-danger" : band.margin < 12 ? "tag-warning" : "tag-success"}`}>
                        {formatPercent(band.margin)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {worstDiscount && (
            <div className="alert-item alert-danger" style={{ marginTop: 12 }}>
              <AlertTriangle size={14} color="#b91c1c" style={{ marginTop: 2, flexShrink: 0 }} />
              <p style={{ fontSize: 11.5, lineHeight: 1.5 }}>
                {worstDiscount.band} discounts lose money: a {formatPercent(worstDiscount.margin)} margin on{" "}
                {formatCurrency(worstDiscount.sales)} of revenue, which is {formatPercent(worstDiscount.share)} of all sales.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Account segments */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div className="panel-header">
          <span className="panel-title">Behavior by account segment</span>
          <span className="tag tag-info">Consumer · Corporate · Home Office</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
          {segment_behavior.map((segment) => (
            <div key={segment.segment} style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 700 }}>{segment.segment}</span>
                <span className="tag tag-info">{formatPercent(segment.revenue_share)} revenue</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 11 }}>
                {[
                  ["Customers", formatNumber(segment.customers)],
                  ["Orders", formatNumber(segment.orders)],
                  ["Avg order", formatCurrency(segment.avg_order_value)],
                  ["Orders / customer", segment.avg_orders_per_customer.toFixed(2)],
                  ["Margin", formatPercent(segment.margin)],
                  ["Revenue", formatCurrency(segment.revenue)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <div style={{ color: "var(--text-muted)", fontSize: 9.5, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>{label}</div>
                    <div style={{ fontWeight: 700, fontSize: 12.5 }}>{value}</div>
                  </div>
                ))}
              </div>
              <div className="progress-track" style={{ height: 4, marginTop: 12 }}>
                <div className="progress-fill" style={{ width: `${segment.revenue_share}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Products + region */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
        <div className="panel animate-fade-up" style={{ flex: "1 1 560px", minWidth: 0, opacity: 0 }}>
          <div className="panel-body" style={{ paddingBottom: 0 }}>
            <div className="panel-header">
              <span className="panel-title">Top products by revenue</span>
              <span className="tag tag-info">Top 8</span>
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th style={{ textAlign: "right" }}>Revenue</th>
                  <th style={{ textAlign: "right" }}>Profit</th>
                  <th style={{ textAlign: "right" }}>Orders</th>
                </tr>
              </thead>
              <tbody>
                {top_products.map((product) => (
                  <tr key={product.name}>
                    <td className="td-primary" style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {product.name}
                    </td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(product.sales)}</td>
                    <td className="td-num" style={{ textAlign: "right", color: product.profit < 0 ? "#b91c1c" : undefined }}>
                      {formatCurrency(product.profit)}
                    </td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatNumber(product.orders)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel panel-body animate-fade-up" style={{ flex: "0 1 300px", minWidth: 240, opacity: 0 }}>
          <div className="panel-header"><span className="panel-title">Regional behavior</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {region_behavior.map((region) => (
              <div key={region.region}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, marginBottom: 4 }}>
                  <span style={{ fontWeight: 600 }}>{region.region}</span>
                  <span style={{ color: "var(--text-muted)" }}>{formatCurrency(region.revenue)}</span>
                </div>
                <div className="progress-track" style={{ height: 5 }}>
                  <div className="progress-fill" style={{ width: `${region.share}%`, background: "#4b5563" }} />
                </div>
                <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3 }}>
                  {formatNumber(region.customers)} customers · {formatNumber(region.orders)} orders
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 14 }}>
        Computed {new Date(data.generated_at).toLocaleString()} from {formatNumber(summary.orders)} orders.
      </div>
    </div>
  );
}
