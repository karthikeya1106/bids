"use client";
import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Title, Tooltip, Legend, Filler, type ChartOptions,
} from "chart.js";
import {
  AlertTriangle, ArrowDownRight, ArrowUpRight, CheckCircle2, Gauge,
  RefreshCw, Sliders, Sparkles, Target, TrendingUp, Zap,
} from "lucide-react";
import { getForecast, getStrategyInsights, postStrategy, postWhatIf } from "@/lib/api";
import { formatCompact, formatCurrency, formatPercent } from "@/lib/format";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

interface ForecastPoint { date: string; value: number; lower?: number; upper?: number }
interface BacktestCandidate { model: string; mape: number | null; mae: number; rmse: number }

interface ForecastData {
  has_data: boolean;
  model: string;
  horizon_months: number;
  historical: { date: string; value: number }[];
  forecast: ForecastPoint[];
  band: string;
  backtest: {
    model: string;
    mape: number | null;
    mae: number | null;
    rmse: number | null;
    holdout_months: number | null;
    candidates: BacktestCandidate[];
    baseline_mape: number | null;
    improvement_vs_naive_pct: number | null;
  };
  drivers: {
    last_actual_month: string;
    last_actual_value: number;
    yoy_value: number | null;
    yoy_pct: number | null;
    recent_growth_pct: number | null;
    trailing_12m_total: number;
    forecast_total: number;
    forecast_vs_trailing_month_avg_pct: number | null;
    seasonal_peak_month: string | null;
    seasonal_peak_factor: number | null;
  };
  category_forecast: {
    category: string; trailing_12m: number; share: number;
    forecast_total: number; forecast_monthly: number; change_pct: number | null;
  }[];
  elasticity: { value: number; method: string; sample: number; r2: number | null };
  gross_margin: number | null;
  defaults: { avg_discount_pct: number; price_elasticity: number; gross_margin_pct: number | null };
}

interface WhatIfResult {
  base_total: number;
  adjusted_total: number;
  impact_pct: number;
  base_profit: number;
  adjusted_profit: number;
  profit_impact: number;
  profit_impact_pct: number;
  adjusted_forecast: ForecastPoint[];
  breakdown: { price: number; discount: number; marketing: number; interaction: number };
  assumptions: {
    price_elasticity: number;
    avg_discount_pct: number;
    new_discount_pct: number;
    gross_margin_pct: number;
    volume_factor: number;
    marketing_lift_pct: number;
    marketing_spend_not_deducted: boolean;
  };
}

interface Play {
  id: string;
  title: string;
  description: string;
  category: string;
  impact_value: number;
  impact_type: string;
  impact_label: string;
  confidence: number;
  risk_level: string;
  horizon: string;
  priority: string;
  evidence: string[];
  actions: string[];
}

interface InsightData {
  has_data: boolean;
  plays: Play[];
  summary: {
    plays: number;
    p1_count: number;
    revenue_opportunity: number;
    profit_opportunity: number;
  } | null;
}

interface AiRecommendation {
  title: string;
  description: string;
  impact: string;
  risk_level: string;
  confidence: number;
  category: string;
  priority: string;
  actions?: string[];
}

const PARAMS = [
  { key: "price_change" as const, label: "Price change", min: -20, max: 20, unit: "%" },
  { key: "discount_change" as const, label: "Discount level", min: -30, max: 30, unit: "%" },
  { key: "marketing_boost" as const, label: "Marketing spend", min: 0, max: 100, unit: "%" },
];

const PRESETS: { label: string; values: { price_change: number; discount_change: number; marketing_boost: number } }[] = [
  { label: "Protect margin", values: { price_change: 4, discount_change: -15, marketing_boost: 0 } },
  { label: "Growth push", values: { price_change: -2, discount_change: 10, marketing_boost: 25 } },
  { label: "Reset", values: { price_change: 0, discount_change: 0, marketing_boost: 0 } },
];

const PRIORITY_TAG: Record<string, string> = { P1: "tag-danger", P2: "tag-warning", P3: "tag-info" };

export default function ForecastingPage() {
  const [horizon, setHorizon] = useState(6);
  const [forecast, setForecast] = useState<ForecastData | null>(null);
  const [whatIf, setWhatIf] = useState<WhatIfResult | null>(null);
  const [insights, setInsights] = useState<InsightData | null>(null);
  const [params, setParams] = useState({ price_change: 0, discount_change: 0, marketing_boost: 0 });
  const [loading, setLoading] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [aiRecs, setAiRecs] = useState<AiRecommendation[]>([]);
  const [aiSource, setAiSource] = useState("");
  const [aiLoading, setAiLoading] = useState(false);

  const reload = () => {
    setLoading(true);
    setWhatIf(null);
    setReloadKey((key) => key + 1);
  };

  useEffect(() => {
    let cancelled = false;
    getForecast(horizon)
      .then((result) => {
        if (cancelled) return;
        setForecast(result);
        setError("");
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the forecast. Make sure the FastAPI server is running on port 8000.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [horizon, reloadKey]);

  useEffect(() => {
    let cancelled = false;
    getStrategyInsights()
      .then((result) => { if (!cancelled) setInsights(result); })
      .catch(() => { /* strategy panel simply stays empty */ });
    return () => { cancelled = true; };
  }, [reloadKey]);

  const runSimulation = async () => {
    setSimulating(true);
    try {
      const result = await postWhatIf({ ...params, horizon_months: horizon });
      setWhatIf(result);
    } finally {
      setSimulating(false);
    }
  };

  const runAiStrategy = async () => {
    setAiLoading(true);
    try {
      const result = await postStrategy();
      const available = Boolean(result.ai_available);
      setAiRecs(available ? result.recommendations ?? [] : []);
      setAiSource(available ? result.generated_by ?? "" : "Gemini key not configured — the measured playbook below is the fallback.");
    } finally {
      setAiLoading(false);
    }
  };

  const header = (
    <div className="page-header" style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="page-title">
            <div className="page-title-icon"><TrendingUp size={18} /></div>
            Forecast &amp; Strategy
          </div>
          <p className="page-subtitle">
            Backtested demand forecast, calibrated what-if simulation, and measured commercial opportunities.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            value={horizon}
            onChange={(event) => {
              setLoading(true);
              setWhatIf(null);
              setHorizon(Number(event.target.value));
            }}
            aria-label="Forecast horizon"
            style={{ fontSize: 12, padding: "7px 10px" }}
          >
            <option value={3}>Next 3 months</option>
            <option value={6}>Next 6 months</option>
            <option value={12}>Next 12 months</option>
          </select>
          <button className="btn-ghost" onClick={reload} style={{ fontSize: 12 }}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>
    </div>
  );

  if (loading && !forecast) {
    return (
      <div>
        {header}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(205px, 1fr))", gap: 14, marginBottom: 14 }}>
          {[...Array(5)].map((_, i) => <div key={i} className="skeleton" style={{ height: 118 }} />)}
        </div>
        <div className="skeleton" style={{ height: 330, marginBottom: 14 }} />
        <div className="skeleton" style={{ height: 240 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "64px 24px" }}>
          <AlertTriangle size={30} color="#b91c1c" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>Forecast unavailable</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 440, margin: "0 auto 18px" }}>{error}</p>
          <button className="btn-primary" onClick={reload}><RefreshCw size={14} /> Try again</button>
        </div>
      </div>
    );
  }

  if (!forecast?.has_data || forecast.historical.length === 0) {
    return (
      <div>
        {header}
        <div className="panel panel-body" style={{ textAlign: "center", padding: "72px 24px" }}>
          <TrendingUp size={28} color="#111111" style={{ margin: "0 auto 12px" }} />
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 6 }}>Not enough history to forecast</div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 430, margin: "0 auto" }}>
            A forecast needs at least four months of orders. Upload a dataset to begin.
          </p>
        </div>
      </div>
    );
  }

  const historical = forecast.historical;
  const forecastPoints = forecast.forecast;
  const adjusted = whatIf?.adjusted_forecast ?? [];
  const dates = [...historical.map((point) => point.date), ...forecastPoints.map((point) => point.date)];
  const historicalValues = historical.map((point) => point.value);
  const nullsForHistory = new Array(historicalValues.length).fill(null);

  const chartData = {
    labels: dates,
    datasets: [
      {
        label: "80% band",
        data: [...nullsForHistory, ...forecastPoints.map((point) => point.lower ?? point.value)],
        borderColor: "transparent",
        backgroundColor: "transparent",
        pointRadius: 0,
        fill: false,
      },
      {
        label: "80% band",
        data: [...nullsForHistory, ...forecastPoints.map((point) => point.upper ?? point.value)],
        borderColor: "transparent",
        backgroundColor: "rgba(17, 17, 17, 0.07)",
        pointRadius: 0,
        fill: "-1",
      },
      {
        label: "Actual",
        data: [...historicalValues, ...new Array(forecastPoints.length).fill(null)],
        borderColor: "#000000",
        backgroundColor: "rgba(0, 0, 0, 0.05)",
        borderWidth: 2.4,
        fill: true,
        tension: 0.32,
        pointRadius: 2,
        pointHoverRadius: 6,
      },
      {
        label: "Forecast",
        data: [...new Array(historicalValues.length).fill(null), ...forecastPoints.map((point) => point.value)],
        borderColor: "#4b5563",
        borderDash: [5, 4],
        borderWidth: 2.2,
        fill: false,
        tension: 0.32,
        pointRadius: 3,
      },
      ...(adjusted.length > 0 ? [{
        label: "What-if",
        data: [...new Array(historicalValues.length).fill(null), ...adjusted.map((point) => point.value)],
        borderColor: "#000000",
        borderDash: [2, 2],
        borderWidth: 2,
        fill: false,
        tension: 0.32,
        pointRadius: 3,
      }] : []),
    ],
  };

  const chartOptions: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        labels: {
          color: "#111111", boxWidth: 12, padding: 16, font: { size: 11, weight: 600 },
          filter: (item, chartDataArg) => {
            const index = chartDataArg.datasets.findIndex((dataset) => dataset.label === item.text);
            return index === 2 || index === 3 || index === 4;
          },
        },
      },
      tooltip: {
        backgroundColor: "#000000",
        padding: 10,
        filter: (item) => !String(item.dataset.label).includes("band"),
        callbacks: {
          label: (context) => ` ${context.dataset.label}: ${formatCurrency(context.parsed.y)}`,
        },
      },
    },
    scales: {
      x: {
        ticks: { color: "#6b7280", maxTicksLimit: 14, font: { size: 10 } },
        grid: { color: "#f3f4f6" },
      },
      y: {
        ticks: { color: "#6b7280", callback: (value) => formatCompact(Number(value)), font: { size: 10 } },
        grid: { color: "#f3f4f6" },
      },
    },
  };

  const mape = forecast.backtest.mape;
  const accuracy = mape === null ? "—" : formatPercent(mape, 1);
  const forecastTotal = forecast.drivers.forecast_total;
  const strategySummary = insights?.summary;

  return (
    <div>
      {header}

      {/* Headline metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(198px, 1fr))", gap: 14, marginBottom: 14 }}>
        {[
          {
            label: "Selected model", value: forecast.model, icon: Gauge,
            sub: `${forecast.backtest.holdout_months ?? "—"}-month holdout · MAPE ${accuracy}`,
          },
          {
            label: `${forecast.horizon_months}-month forecast`, value: formatCompact(forecastTotal), icon: Target,
            sub: forecast.drivers.forecast_vs_trailing_month_avg_pct !== null
              ? `${forecast.drivers.forecast_vs_trailing_month_avg_pct > 0 ? "+" : ""}${forecast.drivers.forecast_vs_trailing_month_avg_pct.toFixed(1)}% vs trailing month average`
              : "Against trailing 12-month average",
          },
          {
            label: "Last actual month", value: formatCompact(forecast.drivers.last_actual_value), icon: TrendingUp,
            sub: forecast.drivers.yoy_pct !== null
              ? `${forecast.drivers.yoy_pct > 0 ? "+" : ""}${forecast.drivers.yoy_pct.toFixed(1)}% year over year`
              : forecast.drivers.last_actual_month,
          },
          {
            label: "Gross margin", value: forecast.gross_margin !== null ? formatPercent(forecast.gross_margin * 100) : "—",
            icon: CheckCircle2,
            sub: `Avg discount ${formatPercent(forecast.defaults.avg_discount_pct)}`,
          },
          {
            label: "Price elasticity", value: forecast.elasticity.value.toFixed(2), icon: Zap,
            sub: forecast.elasticity.method.startsWith("prior") ? "Fallback prior — line-level regression unusable" : forecast.elasticity.method,
          },
        ].map((item, index) => {
          const Icon = item.icon;
          return (
            <div key={item.label} className="kpi-card animate-fade-up" style={{ animationDelay: `${index * 50}ms`, opacity: 0 }}>
              <div className="kpi-accent-bar" />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 9 }}>
                <span className="kpi-label" style={{ marginBottom: 0 }}>{item.label}</span>
                <div className="kpi-icon-box" style={{ width: 29, height: 29 }}><Icon size={13} color="#000000" /></div>
              </div>
              <div className="kpi-value" style={{ fontSize: 21, marginBottom: 5 }}>{item.value}</div>
              <div className="kpi-sub" style={{ lineHeight: 1.45 }}>{item.sub}</div>
            </div>
          );
        })}
      </div>

      {/* Forecast chart */}
      <div className="chart-panel animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
          <div>
            <div className="chart-title">Revenue forecast with 80% band</div>
            <div className="chart-subtitle" style={{ marginBottom: 0 }}>
              {forecast.model} refit on full history · seasonal peak {forecast.drivers.seasonal_peak_month ?? "—"}
              {forecast.drivers.seasonal_peak_factor ? ` (${forecast.drivers.seasonal_peak_factor}× month factor)` : ""}
            </div>
          </div>
          {whatIf && (
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 800,
              color: whatIf.impact_pct >= 0 ? "#047857" : "#b91c1c",
            }}>
              {whatIf.impact_pct >= 0 ? <ArrowUpRight size={15} /> : <ArrowDownRight size={15} />}
              {whatIf.impact_pct > 0 ? "+" : ""}{whatIf.impact_pct.toFixed(1)}% scenario impact
            </div>
          )}
        </div>
        <div style={{ height: 300, marginTop: 14 }}>
          <Line data={chartData} options={chartOptions} />
        </div>
      </div>

      {/* What-if */}
      <div className="panel panel-body animate-fade-up" style={{ marginBottom: 14, opacity: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Sliders size={16} color="#000000" />
            <span style={{ fontWeight: 800, fontSize: 13.5 }}>What-if scenario simulator</span>
            <span className="tag tag-info">elasticity {forecast.elasticity.value.toFixed(2)}</span>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {PRESETS.map((preset) => (
              <button
                key={preset.label}
                className="btn-ghost"
                style={{ fontSize: 11, padding: "5px 10px" }}
                onClick={() => setParams(preset.values)}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 22, marginBottom: 16 }}>
          {PARAMS.map(({ key, label, min, max, unit }) => {
            const value = params[key];
            return (
              <div key={key}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)" }}>{label}</span>
                  <span className="mono" style={{ fontSize: 12.5, fontWeight: 800 }}>
                    {value > 0 ? "+" : ""}{value}{unit}
                  </span>
                </div>
                <input
                  type="range"
                  min={min}
                  max={max}
                  value={value}
                  aria-label={label}
                  onChange={(event) => setParams((current) => ({ ...current, [key]: Number(event.target.value) }))}
                  style={{ width: "100%", accentColor: "#000000", cursor: "pointer" }}
                />
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9.5, color: "var(--text-muted)", marginTop: 2 }}>
                  <span>{min}{unit}</span>
                  <span>0</span>
                  <span>+{max}{unit}</span>
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <button className="btn-primary" onClick={runSimulation} disabled={simulating}>
            <Zap size={13} /> {simulating ? "Simulating…" : "Run simulation"}
          </button>
          {!whatIf && (
            <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
              Baseline {formatCurrency(forecastTotal)} over {forecast.horizon_months} months.
            </span>
          )}
        </div>

        {whatIf && (
          <>
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
              gap: 10, marginTop: 16,
            }}>
              {[
                ["Base revenue", formatCurrency(whatIf.base_total), "var(--text-primary)"],
                ["Scenario revenue", formatCurrency(whatIf.adjusted_total), whatIf.impact_pct >= 0 ? "#047857" : "#b91c1c"],
                ["Profit impact", `${whatIf.profit_impact >= 0 ? "+" : "−"}${formatCurrency(Math.abs(whatIf.profit_impact))}`, whatIf.profit_impact >= 0 ? "#047857" : "#b91c1c"],
                ["Profit change", `${whatIf.profit_impact_pct >= 0 ? "+" : ""}${whatIf.profit_impact_pct.toFixed(1)}%`, whatIf.profit_impact >= 0 ? "#047857" : "#b91c1c"],
              ].map(([label, value, color]) => (
                <div key={label} style={{
                  background: "#f9fafb", border: "1px solid var(--border)",
                  borderRadius: 9, padding: "10px 12px",
                }}>
                  <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)", marginBottom: 3 }}>
                    {label}
                  </div>
                  <div style={{ fontSize: 16, fontWeight: 800, color, fontVariantNumeric: "tabular-nums" }}>{value}</div>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 18, marginTop: 14 }}>
              <div>
                <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 7 }}>
                  Revenue effect by lever
                </div>
                {(["price", "discount", "marketing", "interaction"] as const).map((lever) => {
                  const value = whatIf.breakdown[lever];
                  const max = Math.max(...Object.values(whatIf.breakdown).map((entry) => Math.abs(entry)), 1);
                  return (
                    <div key={lever} style={{ marginBottom: 7 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
                        <span style={{ textTransform: "capitalize", fontWeight: 600 }}>{lever}</span>
                        <span style={{ fontWeight: 700, color: value < 0 ? "#b91c1c" : "#047857" }}>
                          {value < 0 ? "−" : "+"}{formatCompact(Math.abs(value))}
                        </span>
                      </div>
                      <div className="progress-track" style={{ height: 4 }}>
                        <div className="progress-fill" style={{ width: `${(Math.abs(value) / max) * 100}%`, background: value < 0 ? "#9ca3af" : "#111111" }} />
                      </div>
                    </div>
                  );
                })}
              </div>

              <div style={{ fontSize: 10.5, color: "var(--text-secondary)", lineHeight: 1.7 }}>
                <div style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 6 }}>
                  Assumptions
                </div>
                Price elasticity <strong>{whatIf.assumptions.price_elasticity}</strong> · discount{" "}
                {formatPercent(whatIf.assumptions.avg_discount_pct)} → {formatPercent(whatIf.assumptions.new_discount_pct)} · volume factor{" "}
                <strong>{whatIf.assumptions.volume_factor.toFixed(3)}×</strong> · marketing lift{" "}
                {formatPercent(whatIf.assumptions.marketing_lift_pct)} · gross margin {formatPercent(whatIf.assumptions.gross_margin_pct)}.
                {whatIf.assumptions.marketing_spend_not_deducted && (
                  <div style={{ marginTop: 5, color: "#92400e", fontWeight: 600 }}>
                    Marketing spend is not deducted from profit — the profit figure is before campaign cost.
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Backtest + category split */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 14 }}>
        <div className="panel animate-fade-up" style={{ flex: "1 1 430px", minWidth: 0, opacity: 0 }}>
          <div className="panel-body" style={{ paddingBottom: 0 }}>
            <div className="panel-header">
              <span className="panel-title">Model backtest</span>
              <span className="tag tag-info">{forecast.backtest.holdout_months ?? "—"}-month holdout</span>
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th style={{ textAlign: "right" }}>MAPE</th>
                  <th style={{ textAlign: "right" }}>MAE</th>
                  <th style={{ textAlign: "right" }}>RMSE</th>
                </tr>
              </thead>
              <tbody>
                {forecast.backtest.candidates.map((candidate) => (
                  <tr key={candidate.model}>
                    <td className="td-primary">
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                        {candidate.model}
                        {candidate.model === forecast.model && <span className="tag tag-success">Selected</span>}
                      </span>
                    </td>
                    <td className="td-num" style={{ textAlign: "right" }}>{candidate.mape === null ? "—" : formatPercent(candidate.mape, 1)}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(candidate.mae)}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(candidate.rmse)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ padding: "9px 16px", fontSize: 10.5, color: "var(--text-muted)", borderTop: "1px solid var(--border-subtle)" }}>
            {forecast.backtest.improvement_vs_naive_pct !== null
              ? `${formatPercent(forecast.backtest.improvement_vs_naive_pct, 1)} lower error than the seasonal-naive baseline.`
              : "Scored on the most recent months, then refit on the full history."}
          </div>
        </div>

        <div className="panel animate-fade-up" style={{ flex: "1 1 400px", minWidth: 0, opacity: 0 }}>
          <div className="panel-body" style={{ paddingBottom: 0 }}>
            <div className="panel-header">
              <span className="panel-title">Category split</span>
              <span className="tag tag-info">Allocated by trailing mix</span>
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th style={{ textAlign: "right" }}>Share</th>
                  <th style={{ textAlign: "right" }}>Forecast</th>
                  <th style={{ textAlign: "right" }}>Monthly</th>
                  <th style={{ textAlign: "right" }}>Trend</th>
                </tr>
              </thead>
              <tbody>
                {forecast.category_forecast.map((row) => (
                  <tr key={row.category}>
                    <td className="td-primary">{row.category}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatPercent(row.share)}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(row.forecast_total)}</td>
                    <td className="td-num" style={{ textAlign: "right" }}>{formatCurrency(row.forecast_monthly)}</td>
                    <td style={{ textAlign: "right" }}>
                      {row.change_pct === null ? "—" : (
                        <span className={`tag ${row.change_pct >= 0 ? "tag-success" : "tag-warning"}`}>
                          {row.change_pct > 0 ? "+" : ""}{row.change_pct.toFixed(0)}%
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ padding: "9px 16px", fontSize: 10.5, color: "var(--text-muted)", borderTop: "1px solid var(--border-subtle)" }}>
            Category totals allocate the total forecast by trailing-12-month revenue share; trend compares the latest year with the year before.
          </div>
        </div>
      </div>

      {/* Strategy */}
      <div className="panel panel-body animate-fade-up" style={{ opacity: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <Sparkles size={16} color="#000000" />
            <span style={{ fontWeight: 800, fontSize: 13.5 }}>Commercial opportunities</span>
            {strategySummary && (
              <span className="tag tag-info">
                {strategySummary.plays} measured · {strategySummary.p1_count} P1
              </span>
            )}
          </div>
          <button className="btn-primary" onClick={runAiStrategy} disabled={aiLoading} style={{ fontSize: 12 }}>
            <RefreshCw size={12} className={aiLoading ? "animate-spin" : ""} />
            {aiLoading ? "Generating…" : "Generate AI strategy"}
          </button>
        </div>

        {aiSource && aiRecs.length === 0 && (
          <div style={{
            fontSize: 11.5, color: "#92400e", background: "#fffbeb",
            border: "1px solid #fde68a", borderRadius: 8, padding: "7px 10px", marginBottom: 12,
          }}>
            {aiSource}
          </div>
        )}

        {strategySummary && (
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 11.5, color: "var(--text-secondary)", marginBottom: 14 }}>
            <span><strong style={{ color: "#111111" }}>{formatCurrency(strategySummary.revenue_opportunity)}</strong> revenue opportunity</span>
            <span><strong style={{ color: "#111111" }}>{formatCurrency(strategySummary.profit_opportunity)}</strong> profit opportunity</span>
            <span>Sized on trailing 12 months</span>
          </div>
        )}

        {aiRecs.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 8 }}>
              {aiSource || "AI"} recommendations
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
              {aiRecs.map((rec) => (
                <div key={rec.title} style={{
                  border: "1px solid #000000", borderRadius: 11, padding: 13, background: "#ffffff",
                }}>
                  <div style={{ display: "flex", gap: 6, marginBottom: 5, alignItems: "center", flexWrap: "wrap" }}>
                    <span className="tag tag-info">{rec.category}</span>
                    <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{rec.priority} · {rec.risk_level} risk</span>
                  </div>
                  <div style={{ fontSize: 12.5, fontWeight: 800, marginBottom: 4 }}>{rec.title}</div>
                  <p style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.55, marginBottom: 6 }}>{rec.description}</p>
                  <div style={{ fontSize: 11, fontWeight: 700 }}>{rec.impact}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {(!insights || insights.plays.length === 0) ? (
          <p style={{ fontSize: 12.5, color: "var(--text-muted)", padding: "18px 0" }}>
            No measured opportunities available for this dataset yet.
          </p>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 12 }}>
            {insights.plays.map((play) => (
              <div key={play.id} className="strategy-card" style={{ padding: 16 }}>
                <div style={{
                  position: "absolute", top: 0, left: 0, right: 0, height: 3,
                  background: play.priority === "P1" ? "#111111" : "#d1d5db",
                }} />
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                    <span className={`tag ${PRIORITY_TAG[play.priority] ?? "tag-info"}`}>{play.priority}</span>
                    <span className="tag" style={{ background: "#f3f4f6", borderColor: "var(--border)", color: "#111111" }}>{play.category}</span>
                  </div>
                  <span style={{ fontSize: 10.5, color: "var(--text-muted)", whiteSpace: "nowrap" }}>{play.horizon}</span>
                </div>

                <div style={{ fontSize: 13.5, fontWeight: 800, lineHeight: 1.35, marginBottom: 5 }}>{play.title}</div>
                <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.55, marginBottom: 9 }}>
                  {play.description}
                </p>

                <div style={{
                  background: "#f9fafb", border: "1px solid var(--border)",
                  borderRadius: 8, padding: "7px 10px", marginBottom: 9,
                  display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8,
                }}>
                  <span style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>
                    Annual impact
                  </span>
                  <span style={{ fontSize: 12.5, fontWeight: 800 }}>{play.impact_label}</span>
                </div>

                <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 4, marginBottom: 10 }}>
                  {play.evidence.map((line) => (
                    <li key={line} style={{ fontSize: 10.5, color: "var(--text-secondary)", lineHeight: 1.5, display: "flex", gap: 5 }}>
                      <span style={{ width: 4, height: 4, borderRadius: "50%", background: "#9ca3af", marginTop: 6, flexShrink: 0 }} />
                      {line}
                    </li>
                  ))}
                </ul>

                <div style={{ display: "flex", flexDirection: "column", gap: 3, marginBottom: 10 }}>
                  {play.actions.map((action, index) => (
                    <div key={action} style={{ fontSize: 10.5, color: "var(--text-primary)", display: "flex", gap: 6 }}>
                      <span style={{
                        width: 15, height: 15, borderRadius: 4, background: "#f3f4f6",
                        fontSize: 8.5, fontWeight: 800, display: "grid", placeItems: "center", flexShrink: 0,
                      }}>
                        {index + 1}
                      </span>
                      {action}
                    </div>
                  ))}
                </div>

                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, marginBottom: 3 }}>
                    <span style={{ color: "var(--text-muted)" }}>Confidence</span>
                    <span style={{ fontWeight: 800 }}>{formatPercent(play.confidence * 100, 0)}</span>
                  </div>
                  <div className="progress-track" style={{ height: 4 }}>
                    <div className="progress-fill" style={{ width: `${play.confidence * 100}%`, background: "#111111" }} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ marginTop: 14, fontSize: 10.5, color: "var(--text-muted)" }}>
          Opportunities are computed from the loaded orders. AI strategy uses Gemini when a key is configured and falls back to these measured plays otherwise.
        </div>
      </div>
    </div>
  );
}
