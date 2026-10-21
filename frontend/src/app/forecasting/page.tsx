"use client";
import { useEffect, useState } from "react";
import { getForecast, postWhatIf, postStrategy } from "@/lib/api";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Title, Tooltip, Legend, Filler,
} from "chart.js";
import { TrendingUp, Sliders, Sparkles, ArrowUp, ArrowDown, RefreshCw, Zap } from "lucide-react";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

export default function ForecastingPage() {
  const [forecast, setForecast] = useState<any>(null);
  const [whatIf, setWhatIf] = useState<any>(null);
  const [strategies, setStrategies] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [params, setParams] = useState({ price_change: 0, discount_change: 0, marketing_boost: 0 });

  useEffect(() => { getForecast().then(setForecast).finally(() => setLoading(false)); }, []);

  const runWhatIf = async () => {
    const result = await postWhatIf(params);
    setWhatIf(result);
  };

  const runStrategy = async () => {
    setStrategyLoading(true);
    try {
      const r = await postStrategy();
      setStrategies(r.recommendations || []);
    } finally {
      setStrategyLoading(false);
    }
  };

  const buildChart = (data: any) => {
    if (!data) return null;
    const hist = data.historical || [];
    const fore = data.forecast || [];
    const adjFore = data.adjusted_forecast;
    return {
      labels: [...hist.map((h: any) => h.date), ...fore.map((f: any) => f.date)],
      datasets: [
        {
          label: "Historical",
          data: [...hist.map((h: any) => h.value), ...new Array(fore.length).fill(null)],
          borderColor: "#000000",
          backgroundColor: "rgba(0, 0, 0, 0.05)",
          fill: true, tension: 0.35, pointRadius: 2, borderWidth: 2.5,
        },
        {
          label: "Forecast",
          data: [...new Array(hist.length).fill(null), ...fore.map((f: any) => f.value)],
          borderColor: "#4b5563",
          borderDash: [5, 5],
          backgroundColor: "rgba(75, 85, 99, 0.04)",
          fill: true, tension: 0.35, pointRadius: 4, borderWidth: 2,
        },
        ...(adjFore ? [{
          label: "What-If Simulation",
          data: [...new Array(hist.length).fill(null), ...adjFore.map((f: any) => f.value)],
          borderColor: "#000000",
          borderDash: [2, 2],
          fill: false, tension: 0.35, pointRadius: 4, borderWidth: 2,
        }] : []),
      ],
    };
  };

  const chartOptions: any = {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: { color: "#111111", boxWidth: 12, font: { size: 12, weight: "600" }, padding: 14 },
      },
    },
    scales: {
      x: { ticks: { color: "#6b7280", maxTicksLimit: 12, font: { size: 10 } }, grid: { color: "#f3f4f6" } },
      y: { ticks: { color: "#6b7280", callback: (v: any) => "$" + (v / 1000).toFixed(0) + "k", font: { size: 10 } }, grid: { color: "#f3f4f6" } },
    },
  };

  if (loading) return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {[...Array(3)].map((_, i) => <div key={i} className="skeleton" style={{ height: 160, borderRadius: 16 }} />)}
    </div>
  );

  const chartData = buildChart(whatIf || forecast);

  const sliderConfig = [
    { key: "price_change",     label: "Price Change",    min: -30, max: 30,  unit: "%" },
    { key: "discount_change",  label: "Discount Change", min: -20, max: 20,  unit: "%" },
    { key: "marketing_boost",  label: "Marketing Boost", min: 0,   max: 100, unit: "%" },
  ];

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div className="page-title">
          <div className="page-title-icon">
            <TrendingUp size={18} />
          </div>
          Forecasting & Strategy AI
        </div>
        <p className="page-subtitle">XGBoost demand forecasting, What-If simulation, and Gemini AI strategy recommendations</p>
      </div>

      {/* Forecast Chart */}
      <div className="chart-panel animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <div className="chart-title">6-Month Revenue Forecast</div>
            <div className="chart-subtitle">
              Model: <span style={{ color: "#000000", fontWeight: 700 }}>{forecast?.model ?? "Loading…"}</span>
            </div>
          </div>
          {whatIf && (
            <div
              style={{
                display: "flex", alignItems: "center", gap: 6,
                fontSize: 14, fontWeight: 800,
                color: whatIf.impact_pct >= 0 ? "#059669" : "#dc2626",
              }}
            >
              {whatIf.impact_pct >= 0 ? <ArrowUp size={16} /> : <ArrowDown size={16} />}
              {Math.abs(whatIf.impact_pct)}% impact
            </div>
          )}
        </div>
        <div style={{ height: 300 }}>
          {chartData
            ? <Line data={chartData} options={chartOptions} />
            : <p style={{ fontSize: 12, color: "var(--text-muted)", padding: "20px 0" }}>No forecast data. Seed the database first.</p>
          }
        </div>
      </div>

      {/* What-If Simulator */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, animationDelay: "120ms", opacity: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 18 }}>
          <Sliders size={16} color="#000000" />
          <span style={{ fontWeight: 800, fontSize: 13.5, color: "var(--text-primary)" }}>What-If Scenario Simulator</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 24, marginBottom: 18 }}>
          {sliderConfig.map(({ key, label, min, max, unit }) => {
            const val = (params as any)[key];
            return (
              <div key={key}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-secondary)" }}>{label}</span>
                  <span
                    className="mono"
                    style={{ fontSize: 13, fontWeight: 800, color: "#000000" }}
                  >
                    {val > 0 ? "+" : ""}{val}{unit}
                  </span>
                </div>
                <input
                  type="range"
                  min={min}
                  max={max}
                  value={val}
                  onChange={e => setParams(p => ({ ...p, [key]: Number(e.target.value) }))}
                  style={{ width: "100%", accentColor: "#000000", cursor: "pointer" }}
                />
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
                  <span>{min}{unit}</span>
                  <span>0</span>
                  <span>+{max}{unit}</span>
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={runWhatIf} className="btn-primary">
            <Zap size={13} />
            Run Simulation
          </button>
          {whatIf && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, flex: 1 }}>
              <div style={{ background: "#f9fafb", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 14px" }}>
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 3 }}>Base Forecast Total</div>
                <div style={{ fontSize: 15, fontWeight: 800, color: "var(--text-primary)", fontVariantNumeric: "tabular-nums" }}>
                  ${whatIf.base_total?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </div>
              </div>
              <div style={{
                background: whatIf.impact_pct >= 0 ? "#ecfdf5" : "#fef2f2",
                border: `1px solid ${whatIf.impact_pct >= 0 ? "#a7f3d0" : "#fecaca"}`,
                borderRadius: 10, padding: "10px 14px",
              }}>
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 3 }}>Simulated Total</div>
                <div style={{
                  fontSize: 15, fontWeight: 800, fontVariantNumeric: "tabular-nums",
                  color: whatIf.impact_pct >= 0 ? "#065f46" : "#991b1b",
                }}>
                  ${whatIf.adjusted_total?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  <span style={{ fontSize: 12, marginLeft: 6, opacity: 0.85 }}>
                    ({whatIf.impact_pct > 0 ? "+" : ""}{whatIf.impact_pct}%)
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Strategy Recommendations */}
      <div className="panel panel-body animate-fade-up" style={{ animationDelay: "240ms", opacity: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Sparkles size={16} color="#000000" />
            <span style={{ fontWeight: 800, fontSize: 13.5, color: "var(--text-primary)" }}>AI Strategy Recommendations</span>
            <span className="tag" style={{ background: "#f3f4f6", color: "#111111", borderColor: "var(--border)", fontSize: 10, fontWeight: 600 }}>Gemini 1.5 Flash</span>
          </div>
          <button onClick={runStrategy} disabled={strategyLoading} className="btn-primary">
            <RefreshCw size={13} className={strategyLoading ? "animate-spin" : ""} />
            {strategyLoading ? "Generating…" : "Generate Strategies"}
          </button>
        </div>

        {strategies.length === 0 && (
          <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)" }}>
            <Sparkles size={32} style={{ margin: "0 auto 12px", opacity: 0.35, display: "block", color: "#000000" }} />
            <p style={{ fontSize: 13, fontWeight: 500 }}>Click &quot;Generate Strategies&quot; to get AI-powered recommendations</p>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {strategies.map((s: any, i: number) => {
            return (
              <div key={i} className="strategy-card">
                <div style={{
                  position: "absolute", top: 0, left: 0, right: 0, height: 3,
                  background: "#000000",
                }} />

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, marginBottom: 10 }}>
                  <div style={{ fontWeight: 800, fontSize: 13.5, color: "var(--text-primary)", lineHeight: 1.4 }}>
                    {s.title}
                  </div>
                  <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    {s.category && (
                      <span className="tag" style={{ background: "#f3f4f6", color: "#111111", borderColor: "var(--border)", fontSize: 10, fontWeight: 600 }}>
                        {s.category}
                      </span>
                    )}
                    <span className="tag" style={{ background: "#000000", color: "#ffffff", fontSize: 10 }}>
                      {s.risk_level} risk
                    </span>
                  </div>
                </div>

                <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.6, marginBottom: 12 }}>
                  {s.description}
                </p>

                <div
                  style={{
                    background: "#f9fafb", border: "1px solid var(--border)",
                    borderRadius: 8, padding: "8px 12px", marginBottom: 12,
                  }}
                >
                  <div style={{ fontSize: 10, fontWeight: 800, color: "#111111", marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Expected Impact
                  </div>
                  <p style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 500 }}>{s.impact}</p>
                </div>

                {/* Confidence bar */}
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 11 }}>
                    <span style={{ color: "var(--text-muted)" }}>Confidence</span>
                    <span style={{ color: "#000000", fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>
                      {(s.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="progress-track">
                    <div
                      className="progress-fill"
                      style={{ width: `${s.confidence * 100}%`, background: "#000000" }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
