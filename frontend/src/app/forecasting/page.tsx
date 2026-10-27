"use client";
import { useEffect, useRef, useState } from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Title, Tooltip, Legend, Filler, type ChartOptions,
} from "chart.js";
import {
  AlertTriangle, ArrowDownRight, ArrowUpRight, CheckCircle2, Gauge,
  RefreshCw, Sliders, Sparkles, Target, TrendingUp, Zap,
} from "lucide-react";
import {
  getForecast, getStrategyInsights, postOptimize, postStrategy, postStrategyScenarios, postWhatIf,
  type OptimizerResult,
} from "@/lib/api";
import AdaptiveModule, { type AdaptiveModulePayload } from "@/components/AdaptiveModule";
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
  elasticity: {
    value: number;
    measured: boolean;
    method: string;
    reason: string;
    sample: number;
    r2: number | null;
    stderr: number | null;
    band: [number, number];
  };
  gross_margin: number | null;
  defaults: {
    avg_discount_pct: number;
    price_elasticity: number;
    elasticity_measured: boolean;
    elasticity_band: [number, number] | null;
    elasticity_reason: string | null;
    gross_margin_pct: number | null;
  };
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
  elasticity: {
    value: number;
    value_used: number;
    measured: boolean;
    method: string;
    reason: string;
    sample: number;
    r2: number | null;
    overridden_for_sensitivity: boolean;
  };
  marketing_spend: { basis: number; incremental: number; charged: boolean };
  assumptions: {
    price_elasticity: number;
    elasticity_measured: boolean;
    elasticity_source: string;
    elasticity_sample: number | null;
    elasticity_r2: number | null;
    elasticity_note: string | null;
    avg_discount_pct: number;
    new_discount_pct: number;
    gross_margin_pct: number;
    volume_factor: number;
    marketing_lift_pct: number;
    marketing_spend_basis: number;
    incremental_marketing_spend: number;
    marketing_spend_not_deducted: boolean;
  };
}

/** One play evaluated through the demand simulator for the forecast horizon. */
interface PlayScenario {
  available: boolean;
  reason?: string;
  levers?: { price_change: number; discount_change: number; marketing_boost: number };
  rationale?: string;
  horizon_months?: number;
  base_revenue?: number;
  scenario_revenue?: number;
  revenue_impact?: number;
  revenue_impact_pct?: number;
  base_profit?: number;
  scenario_profit?: number;
  profit_impact?: number;
  profit_impact_pct?: number;
  marketing_cost?: number;
  sensitivity?: {
    elasticity_low: number;
    elasticity_central: number;
    elasticity_high: number;
    revenue_impact_range: [number, number];
    profit_impact_range: [number, number];
    basis: string;
  };
  assumptions?: Record<string, string | number | boolean | null>;
}

interface ScenarioData {
  has_data?: boolean;
  available: boolean;
  reason?: string;
  horizon_months?: number;
  plays: Record<string, PlayScenario>;
  simulation: {
    baseline_revenue: number | null;
    horizon_months: number;
    model: string | null;
    marketing_spend_basis: number;
    marketing_spend_charged: boolean;
    elasticity: {
      value: number | null;
      measured: boolean;
      method: string | null;
      sample: number | null;
      r2: number | null;
      stderr: number | null;
      band: [number, number] | null;
      reason: string | null;
    };
    plays_simulated: number;
    plays_without_scenario: number;
  } | null;
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

/** "+$1,240" / "−$860" for a signed money delta. */
function signedCurrency(value: number | null | undefined): string {
  const amount = value ?? 0;
  return `${amount >= 0 ? "+" : "−"}${formatCurrency(Math.abs(amount))}`;
}

function signedPercent(value: number | null | undefined): string {
  const amount = value ?? 0;
  return `${amount > 0 ? "+" : ""}${amount.toFixed(1)}%`;
}

export default function ForecastingPage() {
  const [horizon, setHorizon] = useState(6);
  const [forecast, setForecast] = useState<ForecastData | null>(null);
  const [whatIf, setWhatIf] = useState<WhatIfResult | null>(null);
  const [insights, setInsights] = useState<InsightData | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioData | null>(null);
  const [params, setParams] = useState({ price_change: 0, discount_change: 0, marketing_boost: 0 });
  // Current marketing spend over the horizon; charged to profit when a boost is
  // simulated. Held in a ref as well so scenario reloads use the latest value.
  const [spend, setSpend] = useState(0);
  const [loading, setLoading] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [aiRecs, setAiRecs] = useState<AiRecommendation[]>([]);
  const [aiSource, setAiSource] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [optimum, setOptimum] = useState<OptimizerResult | null>(null);
  const [optimising, setOptimising] = useState(false);
  const [optimumError, setOptimumError] = useState("");
  // A scenario fetch always follows on mount, so start in the loading state.
  const [scenariosLoading, setScenariosLoading] = useState(true);

  const reload = () => {
    setLoading(true);
    setWhatIf(null);
    setOptimum(null);
    setOptimumError("");
    setReloadKey((key) => key + 1);
  };

  const spendValue = Number.isFinite(spend) ? Math.max(spend, 0) : 0;
  const spendRef = useRef(0);

  const refreshScenarios = async (spendBasis: number) => {
    setScenariosLoading(true);
    try {
      const result = await postStrategyScenarios({
        horizon_months: horizon,
        marketing_spend: spendBasis,
      });
      setScenarios(result as ScenarioData);
    } catch {
      setScenarios(null);
    } finally {
      setScenariosLoading(false);
    }
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

  // Scenarios are fetched when the page or horizon changes, using the latest
  // spend baseline without re-fetching on every keystroke in the input.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await postStrategyScenarios({
          horizon_months: horizon,
          marketing_spend: spendRef.current,
        });
        if (!cancelled) setScenarios(result as ScenarioData);
      } catch {
        if (!cancelled) setScenarios(null);
      } finally {
        if (!cancelled) setScenariosLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [horizon, reloadKey]);

  const runSimulation = async () => {
    setSimulating(true);
    try {
      const result = await postWhatIf({ ...params, horizon_months: horizon, marketing_spend: spendValue });
      setWhatIf(result);
      // The play scenarios use the same spend baseline and elasticity.
      await refreshScenarios(spendValue);
    } finally {
      setSimulating(false);
    }
  };

  const runOptimiser = async () => {
    setOptimising(true);
    setOptimumError("");
    try {
      const result = await postOptimize({ horizon_months: horizon, marketing_spend: spendValue });
      if (!result.has_data || !result.best) {
        setOptimum(null);
        setOptimumError(result.error || "No lever combination could be evaluated on this dataset.");
        return;
      }
      setOptimum(result);
      // Put the recommendation into the simulator, so running it shows the full
      // breakdown for exactly the levers that were recommended.
      setParams({
        price_change: result.best.price_change,
        discount_change: result.best.discount_change,
        marketing_boost: result.best.marketing_boost,
      });
    } catch {
      setOptimum(null);
      setOptimumError("Could not run the optimiser. Check that the API server is running.");
    } finally {
      setOptimising(false);
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

  const adaptive = forecast && (forecast as { mode?: string }).mode === "adaptive"
    ? (forecast as unknown as AdaptiveModulePayload)
    : null;

  const header = (
    <div className="page-header" style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="page-title">
            <div className="page-title-icon"><TrendingUp size={18} /></div>
            Forecast &amp; Strategy
          </div>
          <p className="page-subtitle">
            {adaptive
              ? "Prediction and forecasting selected from what this dataset can actually support."
              : "Backtested demand forecast, calibrated what-if simulation, and measured commercial opportunities."}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {!adaptive && (
            <select
              value={horizon}
              onChange={(event) => {
                setLoading(true);
                setWhatIf(null);
                setOptimum(null);
                setOptimumError("");
                setHorizon(Number(event.target.value));
              }}
              aria-label="Forecast horizon"
              style={{ fontSize: 12, padding: "7px 10px" }}
            >
              <option value={3}>Next 3 months</option>
              <option value={6}>Next 6 months</option>
              <option value={12}>Next 12 months</option>
            </select>
          )}
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

  if (adaptive) {
    return (
      <div>
        {header}
        <AdaptiveModule payload={adaptive} onRefresh={reload} />
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
            {forecast.elasticity.measured ? (
              <span
                className="tag tag-success"
                title={forecast.elasticity.reason}
              >
                measured on {forecast.elasticity.sample.toLocaleString()} order lines
                {forecast.elasticity.r2 !== null ? ` · R² ${forecast.elasticity.r2.toFixed(2)}` : ""}
              </span>
            ) : (
              <span
                className="tag tag-warning"
                title={forecast.elasticity.reason}
              >
                assumed, not measured
              </span>
            )}
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

        {!forecast.elasticity.measured && (
          <div style={{
            fontSize: 11, color: "#92400e", background: "#fffbeb", border: "1px solid #fde68a",
            borderRadius: 8, padding: "8px 10px", marginBottom: 14, lineHeight: 1.55,
          }}>
            <strong>Elasticity is assumed, not measured.</strong>{" "}
            {forecast.elasticity.reason}. Every number below is scaled by the {forecast.elasticity.value.toFixed(2)}{" "}
            prior, and the results before and after your change use the same assumption, so read
            them as direction and rough size, not as a calibrated forecast of the response.
          </div>
        )}

        <div style={{ display: "flex", alignItems: "flex-end", gap: 14, flexWrap: "wrap", marginBottom: 16 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 220 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-secondary)" }}>
              Marketing spend over the horizon (optional)
            </span>
            <input
              type="number"
              min={0}
              step={100}
              value={spend === 0 ? "" : spend}
              placeholder="0 — not charged"
              onChange={(event) => {
                const value = Number(event.target.value);
                const next = Number.isFinite(value) && value > 0 ? value : 0;
                spendRef.current = next;
                setSpend(next);
              }}
              style={{ fontSize: 12.5, padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border)" }}
            />
            <span style={{ fontSize: 10.5, color: "var(--text-muted)", lineHeight: 1.5 }}>
              A boost only costs profit when this baseline is set; the incremental spend is then
              deducted. Baseline spend is not in the order log, so it is excluded from both sides.
            </span>
          </label>
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

        <div style={{
          marginTop: 18, border: "1px solid var(--border)", borderRadius: 10,
          background: "#fafafa", padding: "14px 16px",
        }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <div style={{ minWidth: 240 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 800 }}>
                <Target size={14} /> Recommended levers
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3, lineHeight: 1.55, maxWidth: 470 }}>
                Instead of scoring the dials above, this searches the same simulator for the
                combination with the best net profit and loads it into the simulator.
              </div>
            </div>
            <button className="btn-ghost" onClick={runOptimiser} disabled={optimising} style={{ fontSize: 12, gap: 6 }}>
              <Sparkles size={13} /> {optimising ? "Searching…" : optimum ? "Search again" : "Find the best levers"}
            </button>
          </div>

          {optimumError && (
            <div style={{ fontSize: 11.5, color: "#b91c1c", marginTop: 10 }}>{optimumError}</div>
          )}

          {optimum?.best && (() => {
            const best = optimum.best;
            const cards = [
              ["Price", signedPercent(best.price_change), "var(--text-primary)"],
              ["Discount level", signedPercent(best.discount_change), "var(--text-primary)"],
              ["Marketing", `${best.marketing_boost > 0 ? "+" : ""}${best.marketing_boost}%`, "var(--text-primary)"],
              ["Profit impact", `${best.profit_impact >= 0 ? "+" : "−"}${formatCurrency(Math.abs(best.profit_impact))}`, best.profit_impact >= 0 ? "#047857" : "#b91c1c"],
              ["Revenue impact", signedPercent(best.revenue_impact_pct), best.revenue_impact_pct >= 0 ? "#047857" : "#b91c1c"],
            ];
            return (
              <div style={{ marginTop: 12 }}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8 }}>
                  {cards.map(([label, value, color]) => (
                    <div key={label} style={{ background: "#ffffff", border: "1px solid var(--border)", borderRadius: 8, padding: "9px 11px" }}>
                      <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)", marginBottom: 2 }}>{label}</div>
                      <div style={{ fontSize: 14.5, fontWeight: 800, color, fontVariantNumeric: "tabular-nums" }}>{value}</div>
                    </div>
                  ))}
                </div>

                <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 9, lineHeight: 1.6 }}>
                  Best of {optimum.search.combinations.toLocaleString()} combinations, scored at{" "}
                  {optimum.elasticity.measured ? "the measured" : "an assumed"} elasticity of{" "}
                  {optimum.elasticity.value?.toFixed(2) ?? "—"}. Loaded into the simulator — run it to see the
                  full breakdown and bands.
                  {best.incremental_marketing_spend > 0 && (
                    <> Incremental marketing spend of {formatCurrency(best.incremental_marketing_spend)} is charged to profit.</>
                  )}
                  {best.marketing_boost > 0 && best.incremental_marketing_spend <= 0 && (
                    <> Its marketing boost is not charged to profit — enter a spend baseline above to include campaign cost.</>
                  )}
                  {optimum.constraint && optimum.best_unconstrained && optimum.best_unconstrained.profit_impact > best.profit_impact + 1 && (
                    <> The unconstrained best ({signedPercent(optimum.best_unconstrained.revenue_impact_pct)} revenue)
                    was not used because it breaks the revenue floor.</>
                  )}
                </div>

                {optimum.alternatives.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 5 }}>
                      Next best combinations
                    </div>
                    {optimum.alternatives.slice(0, 3).map((row, index) => (
                      <div
                        key={`${row.price_change}-${row.discount_change}-${row.marketing_boost}`}
                        style={{
                          display: "flex", justifyContent: "space-between", gap: 10, fontSize: 11,
                          padding: "5px 0", borderTop: index === 0 ? "none" : "1px solid var(--border)",
                        }}
                      >
                        <span style={{ color: "var(--text-secondary)" }}>
                          Price {signedPercent(row.price_change)} · discount {signedPercent(row.discount_change)} · marketing +{row.marketing_boost}%
                        </span>
                        <span className="mono" style={{ fontWeight: 700, color: row.profit_impact >= 0 ? "#047857" : "#b91c1c" }}>
                          {row.profit_impact >= 0 ? "+" : "−"}{formatCurrency(Math.abs(row.profit_impact))}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}
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
                Price elasticity <strong>{whatIf.assumptions.price_elasticity}</strong>{" "}
                ({whatIf.assumptions.elasticity_measured
                  ? `measured on ${(whatIf.assumptions.elasticity_sample ?? 0).toLocaleString()} order lines`
                  : "assumed prior"}) · discount{" "}
                {formatPercent(whatIf.assumptions.avg_discount_pct)} → {formatPercent(whatIf.assumptions.new_discount_pct)} · volume factor{" "}
                <strong>{whatIf.assumptions.volume_factor.toFixed(3)}×</strong> · marketing lift{" "}
                {formatPercent(whatIf.assumptions.marketing_lift_pct)} · gross margin {formatPercent(whatIf.assumptions.gross_margin_pct)}.
                {whatIf.marketing_spend.charged ? (
                  <div style={{ marginTop: 5, color: "#065f46", fontWeight: 600 }}>
                    Incremental marketing spend of {""}
                    {formatCurrency(whatIf.marketing_spend.incremental)} is deducted from profit.
                  </div>
                ) : whatIf.assumptions.marketing_spend_not_deducted ? (
                  <div style={{ marginTop: 5, color: "#92400e", fontWeight: 600 }}>
                    Marketing spend is not deducted from profit — no spend baseline was supplied, so
                    the profit figure is before campaign cost.
                  </div>
                ) : null}
                {!whatIf.elasticity.measured && (
                  <div style={{ marginTop: 5, color: "#92400e", fontWeight: 600 }}>
                    The elasticity was assumed ({whatIf.elasticity.reason}), so the response is a
                    direction and rough size, not a calibrated prediction.
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
            {scenarios?.simulation && (
              <span>
                <strong style={{ color: "#111111" }}>{scenarios.simulation.plays_simulated}</strong> of{" "}
                {insights?.plays.length ?? 0} plays simulated over {scenarios.horizon_months} months ·{" "}
                {scenarios.simulation.elasticity.measured ? "measured" : "assumed"} elasticity
              </span>
            )}
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
            {insights.plays.map((play) => {
              const scenario = scenarios?.plays?.[play.id];
              return (
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

                <div style={{
                  border: `1px solid ${scenario?.available ? "#a7f3d0" : "var(--border)"}`,
                  background: scenario?.available ? "#ecfdf5" : "#f9fafb",
                  borderRadius: 8, padding: "8px 10px", marginBottom: 9,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>
                      Scenario · {scenarios?.horizon_months ?? horizon} months
                    </span>
                    {scenario?.available && (
                      <span style={{ fontSize: 9, fontWeight: 700, color: "#065f46", whiteSpace: "nowrap" }}>
                        {scenarios?.simulation?.elasticity.measured ? "measured elasticity" : "assumed elasticity"}
                      </span>
                    )}
                  </div>

                  {scenario?.available ? (
                    <>
                      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 11.5 }}>
                        <span>
                          Revenue{" "}
                          <strong style={{ color: (scenario.revenue_impact ?? 0) >= 0 ? "#047857" : "#b91c1c" }}>
                            {signedCurrency(scenario.revenue_impact)}
                          </strong>{" "}
                          <span style={{ color: "var(--text-muted)" }}>({signedPercent(scenario.revenue_impact_pct)})</span>
                        </span>
                        <span>
                          Net profit{" "}
                          <strong style={{ color: (scenario.profit_impact ?? 0) >= 0 ? "#047857" : "#b91c1c" }}>
                            {signedCurrency(scenario.profit_impact)}
                          </strong>
                        </span>
                      </div>
                      {scenario.sensitivity && (
                        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4, lineHeight: 1.5 }}>
                          Range across the elasticity band ({scenario.sensitivity.elasticity_low} to{" "}
                          {scenario.sensitivity.elasticity_high}): revenue{" "}
                          {signedCurrency(scenario.sensitivity.revenue_impact_range[0])} to{" "}
                          {signedCurrency(scenario.sensitivity.revenue_impact_range[1])}, profit{" "}
                          {signedCurrency(scenario.sensitivity.profit_impact_range[0])} to{" "}
                          {signedCurrency(scenario.sensitivity.profit_impact_range[1])}.{" "}
                          {scenario.sensitivity.basis}.
                        </div>
                      )}
                      {scenario.levers && (
                        <div style={{ fontSize: 10, color: "var(--text-secondary)", marginTop: 4 }}>
                          Modelled as price {signedPercent(scenario.levers.price_change)} · discount{" "}
                          {signedPercent(scenario.levers.discount_change)} · marketing +{" "}
                          {scenario.levers.marketing_boost}%.
                        </div>
                      )}
                      {scenario.rationale && (
                        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3, lineHeight: 1.5 }}>
                          {scenario.rationale}
                        </div>
                      )}
                      {scenario.assumptions?.marketing_spend_not_deducted === true && (
                        <div style={{ fontSize: 10, color: "#92400e", marginTop: 4, fontWeight: 600 }}>
                          Marketing spend is not charged to this profit — provide a spend baseline in the
                          simulator above to include it.
                        </div>
                      )}
                    </>
                  ) : (
                    <div style={{ fontSize: 10.5, color: "var(--text-muted)", lineHeight: 1.5 }}>
                      {scenario?.reason
                        ?? (scenariosLoading
                          ? "Simulating this play…"
                          : scenarios?.available === false
                            ? scenarios.reason
                            : "No simulator scenario for this play.")}
                    </div>
                  )}
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
              );
            })}
          </div>
        )}

        <div style={{ marginTop: 14, fontSize: 10.5, color: "var(--text-muted)" }}>
          Opportunities are computed from the loaded orders. AI strategy uses Gemini when a key is configured and falls back to these measured plays otherwise.
        </div>
      </div>
    </div>
  );
}
