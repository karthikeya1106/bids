"""
Revenue forecasting and what-if simulation.

Forecasts are produced by three candidate models, backtested on the last months
of history, and the winner (lowest holdout MAPE) is refit on the full series:

* **XGBoost** with calendar, lag and rolling features (recursive multi-step).
* **Seasonal + trend** — multiplicative month factors over a linear trend.
* **Seasonal naive** — repeat the same month one year earlier.

The reported accuracy is the holdout MAPE, not an in-sample fit statistic. The
what-if simulator uses a price elasticity estimated from the order lines, so the
revenue response is calibrated to the actual data rather than a fixed guess.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

HORIZON_DEFAULT = 6
BAND_Z = 1.28  # ~80% interval under normally distributed residuals


# ── feature engineering ──────────────────────────────────────────────────────
def create_features(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["month"] = work["ds"].dt.month
    work["quarter"] = work["ds"].dt.quarter
    work["year"] = work["ds"].dt.year
    work["month_sin"] = np.sin(2 * np.pi * work["month"] / 12)
    work["month_cos"] = np.cos(2 * np.pi * work["month"] / 12)
    for lag in (1, 2, 3, 6, 12):
        work[f"lag_{lag}"] = work["y"].shift(lag)
    work["rolling_3"] = work["y"].shift(1).rolling(3).mean()
    work["rolling_6"] = work["y"].shift(1).rolling(6).mean()
    return work.dropna()


FEATURE_COLUMNS = [
    "month", "quarter", "year", "month_sin", "month_cos",
    "lag_1", "lag_2", "lag_3", "lag_6", "rolling_3", "rolling_6",
]


def _prepare(monthly_df: pd.DataFrame) -> pd.DataFrame:
    df = monthly_df[["ds", "y"]].copy()
    df["ds"] = pd.to_datetime(df["ds"])
    numeric = pd.to_numeric(df["y"], errors="coerce")
    df["y"] = numeric
    return df.dropna(subset=["y"]).sort_values("ds").reset_index(drop=True)


# ── candidate models ─────────────────────────────────────────────────────────
def _xgb_forecast(df: pd.DataFrame, horizon: int) -> np.ndarray:
    from xgboost import XGBRegressor

    feature_df = create_features(df)
    if len(feature_df) < 6:
        raise ValueError("insufficient history for XGBoost")

    model = XGBRegressor(
        n_estimators=250,
        learning_rate=0.05,
        max_depth=3,
        subsample=0.85,
        colsample_bytree=0.85,
        random_state=42,
        verbosity=0,
    )
    model.fit(feature_df[FEATURE_COLUMNS], feature_df["y"])

    last_date = df["ds"].max()
    future_dates = [last_date + pd.DateOffset(months=i + 1) for i in range(horizon)]
    combined = pd.concat(
        [df, pd.DataFrame({"ds": future_dates, "y": np.nan})], ignore_index=True
    )

    for position in range(len(df), len(combined)):
        features = create_features(combined.iloc[: position + 1])
        if features.empty:
            combined.at[position, "y"] = float(df["y"].tail(3).mean())
            continue
        row = features.iloc[-1][FEATURE_COLUMNS].to_numpy().reshape(1, -1)
        combined.at[position, "y"] = max(float(model.predict(row)[0]), 0.0)

    return combined.tail(horizon)["y"].to_numpy(dtype=float)


def _seasonal_factors(ds: pd.Series, values: pd.Series) -> Dict[int, float]:
    trend = values.rolling(12, center=True, min_periods=6).mean()
    detrended = (values / trend.replace(0, np.nan)).to_numpy()
    calendar = pd.to_datetime(ds).dt.month.to_numpy()
    factors: Dict[int, float] = {}
    for month in range(1, 13):
        subset = detrended[calendar == month]
        subset = subset[~np.isnan(subset)]
        if len(subset):
            factors[month] = float(np.clip(np.median(subset), 0.55, 1.8))
    return factors


def _seasonal_trend_forecast(df: pd.DataFrame, horizon: int) -> np.ndarray:
    factors = _seasonal_factors(df["ds"], df["y"])
    if not factors:
        factors = {month: 1.0 for month in range(1, 13)}

    seasonal = df["ds"].dt.month.map(lambda month: factors.get(int(month), 1.0)).to_numpy()
    deseasonalized = df["y"].to_numpy() / seasonal
    x = np.arange(len(deseasonalized))
    slope, intercept = np.polyfit(x, deseasonalized, 1)

    last_date = df["ds"].max()
    predictions = []
    for step in range(1, horizon + 1):
        future_date = last_date + pd.DateOffset(months=step)
        factor = factors.get(future_date.month, 1.0)
        predictions.append(max((intercept + slope * (len(deseasonalized) + step - 1)) * factor, 0.0))
    return np.asarray(predictions, dtype=float)


def _seasonal_naive_forecast(df: pd.DataFrame, horizon: int) -> np.ndarray:
    values = df["y"].to_numpy(dtype=float)
    predictions = []
    for step in range(1, horizon + 1):
        index = len(values) - 12 + (step - 1)
        predictions.append(float(values[index]) if index >= 0 else float(np.mean(values[-3:])))
    return np.asarray(predictions, dtype=float)


MODELS = {
    "XGBoost": _xgb_forecast,
    "Seasonal + trend": _seasonal_trend_forecast,
    "Seasonal naive": _seasonal_naive_forecast,
}


# ── backtesting ──────────────────────────────────────────────────────────────
def _mape(actual: np.ndarray, predicted: np.ndarray) -> Optional[float]:
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100)


def _backtest(df: pd.DataFrame, horizon: int) -> tuple[Optional[str], List[Dict], Dict]:
    """
    Hold out the last ``horizon`` months, score every model, return the winner.

    The winner is refit on the full history by the caller.
    """
    horizon = max(2, min(horizon, max(2, len(df) // 4)))
    if len(df) <= horizon + 8:
        return None, [], {}

    train = df.iloc[:-horizon]
    actual = df["y"].to_numpy(dtype=float)[-horizon:]
    results: List[Dict] = []
    details: Dict[str, Dict] = {}

    for name, builder in MODELS.items():
        try:
            predicted = builder(train, horizon)
        except Exception as exc:  # pragma: no cover - defensive
            details[name] = {"error": str(exc)}
            continue
        if len(predicted) != horizon or np.isnan(predicted).any():
            continue
        errors = actual - predicted
        mape = _mape(actual, predicted)
        result = {
            "model": name,
            "mape": round(mape, 2) if mape is not None else None,
            "mae": round(float(np.mean(np.abs(errors))), 2),
            "rmse": round(float(np.sqrt(np.mean(errors ** 2))), 2),
        }
        results.append(result)
        details[name] = {"predicted": predicted, "errors": errors}

    scored = [r for r in results if r["mape"] is not None]
    if not scored:
        return None, results, details

    winner = min(scored, key=lambda item: item["mape"])
    chosen_details = details.get(winner["model"], {})
    return winner["model"], results, {
        "errors": chosen_details.get("errors", np.array([])),
        "mape": winner["mape"],
        "mae": winner["mae"],
        "rmse": winner["rmse"],
        "holdout": horizon,
    }


def _elasticity(df: pd.DataFrame) -> Dict:
    """
    Estimate price elasticity from order lines: log(quantity) ~ log(unit price).

    Falls back to a category-agnostic prior when the regression is unusable
    (fewer than 60 usable lines or a non-negative slope).
    """
    if df.empty or not {"sales", "quantity"}.issubset(df.columns):
        return {"value": -1.2, "method": "prior (no order lines)", "sample": 0, "r2": None}

    work = df[(df["sales"] > 0) & (df["quantity"] > 0)].copy()
    work["unit_price"] = work["sales"] / work["quantity"]
    work = work[(work["unit_price"] > 0.01) & work["unit_price"].notna()]
    if len(work) < 60:
        return {"value": -1.2, "method": "prior (too few lines)", "sample": int(len(work)), "r2": None}

    x = np.log(work["unit_price"].to_numpy(dtype=float))
    y = np.log(work["quantity"].to_numpy(dtype=float))
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else None

    if not np.isfinite(slope) or slope >= -0.05:
        return {"value": -1.2, "method": "prior (regression unusable)", "sample": int(len(work)), "r2": round(r2, 3) if r2 else None}

    return {
        "value": round(float(np.clip(slope, -4.0, -0.1)), 2),
        "method": "OLS on log(quantity) vs log(unit price)",
        "sample": int(len(work)),
        "r2": round(float(r2), 3) if r2 is not None else None,
    }


# ── public API ───────────────────────────────────────────────────────────────
def forecast_sales(
    monthly_df: pd.DataFrame,
    horizon_months: int = HORIZON_DEFAULT,
    orders_df: Optional[pd.DataFrame] = None,
) -> Dict:
    """Forecast revenue for ``horizon_months`` with a backtested model."""
    df = _prepare(monthly_df)
    if len(df) < 4:
        return {
            "has_data": False,
            "historical": [],
            "forecast": [],
            "model": "Insufficient history",
            "horizon_months": horizon_months,
        }

    winner, results, best = _backtest(df, horizon_months)

    if winner is None:
        winner = "Seasonal + trend"
        results = []
        best = {}

    try:
        forecast_values = MODELS[winner](df, horizon_months)
    except Exception:
        winner = "Seasonal + trend"
        forecast_values = _seasonal_trend_forecast(df, horizon_months)

    # Residual scale: prefer holdout errors, else in-sample residual of the fit.
    errors = best.get("errors")
    if errors is not None and len(errors) >= 2:
        sigma = float(np.sqrt(np.mean(np.asarray(errors) ** 2)))
    else:
        sigma = float(np.std(df["y"].to_numpy(dtype=float))) * 0.4
    sigma = sigma if sigma > 0 else float(np.mean(df["y"])) * 0.1

    last_date = df["ds"].max()
    forecast = []
    for step, value in enumerate(forecast_values, start=1):
        date = last_date + pd.DateOffset(months=step)
        spread = sigma * np.sqrt(1 + step / 12) * BAND_Z
        forecast.append(
            {
                "date": date.strftime("%Y-%m"),
                "value": round(float(value), 2),
                "lower": round(max(float(value) - spread, 0.0), 2),
                "upper": round(float(value) + spread, 2),
            }
        )

    historical = [
        {"date": row.ds.strftime("%Y-%m"), "value": round(float(row.y), 2)}
        for row in df.itertuples(index=False)
    ]

    # Context the UI shows next to the forecast line.
    y = df["y"].to_numpy(dtype=float)
    trail_12 = float(np.sum(y[-12:]))
    trail_3 = float(np.mean(y[-3:]))
    prior_3 = float(np.mean(y[-6:-3])) if len(y) >= 6 else trail_3
    recent_growth = round((trail_3 - prior_3) / abs(prior_3) * 100, 1) if prior_3 else None

    last_date = df["ds"].max()
    yoy_value = None
    yoy_month = last_date - pd.DateOffset(months=12)
    match = df[df["ds"].dt.to_period("M") == yoy_month.to_period("M")]
    if not match.empty:
        yoy_value = float(match["y"].iloc[-1])

    forecast_total = float(sum(item["value"] for item in forecast))
    forecast_avg = forecast_total / max(len(forecast), 1)

    factors = _seasonal_factors(df["ds"], df["y"])
    peak_month = max(factors, key=factors.get) if factors else None

    drivers = {
        "last_actual_month": historical[-1]["date"],
        "last_actual_value": historical[-1]["value"],
        "yoy_value": round(yoy_value, 2) if yoy_value is not None else None,
        "yoy_pct": round((y[-1] - yoy_value) / abs(yoy_value) * 100, 1) if yoy_value else None,
        "recent_growth_pct": recent_growth,
        "trailing_12m_total": round(trail_12, 2),
        "forecast_total": round(forecast_total, 2),
        "forecast_vs_trailing_month_avg_pct": round(
            (forecast_avg - trail_12 / 12) / (trail_12 / 12) * 100, 1
        ) if trail_12 else None,
        "seasonal_peak_month": pd.Timestamp(2024, peak_month, 1).strftime("%B") if peak_month else None,
        "seasonal_peak_factor": round(factors.get(peak_month, 1.0), 2) if peak_month else None,
    }

    category_forecast = []
    if orders_df is not None and not orders_df.empty and "category" in orders_df.columns:
        work = orders_df.copy()
        work["month"] = work["order_date"].dt.to_period("M").astype(str)
        recent_start = str((last_date - pd.DateOffset(months=11)).to_period("M"))
        recent = work[work["month"] >= recent_start]
        mixed = recent.groupby("category")["sales"].sum().sort_values(ascending=False)
        total_recent = float(mixed.sum())
        prior_recent = work[
            (work["month"] >= str((last_date - pd.DateOffset(months=23)).to_period("M")))
            & (work["month"] < recent_start)
        ]
        prior_mix = prior_recent.groupby("category")["sales"].sum()

        for category, sales in mixed.items():
            share = float(sales / total_recent) if total_recent else 0.0
            prior_value = float(prior_mix.get(category, 0.0)) / 12.0 if len(prior_mix) else 0.0
            category_forecast.append(
                {
                    "category": str(category),
                    "trailing_12m": round(float(sales), 2),
                    "share": round(share * 100, 1),
                    "forecast_total": round(forecast_total * share, 2),
                    "forecast_monthly": round(forecast_avg * share, 2),
                    "change_pct": round((float(sales) / 12 - prior_value) / abs(prior_value) * 100, 1)
                    if prior_value else None,
                }
            )

    elasticity = _elasticity(orders_df) if orders_df is not None else {"value": -1.2, "method": "prior", "sample": 0, "r2": None}
    gross_margin = None
    if orders_df is not None and not orders_df.empty and "profit" in orders_df.columns:
        total_sales = float(orders_df["sales"].sum())
        if total_sales:
            gross_margin = round(float(orders_df["profit"].sum()) / total_sales, 4)
    avg_discount = (
        float(np.average(orders_df["discount"], weights=orders_df["sales"]))
        if orders_df is not None and not orders_df.empty and "discount" in orders_df.columns and orders_df["sales"].sum() > 0
        else 0.0
    )

    best_mape = best.get("mape")
    naive = next((r for r in results if r["model"] == "Seasonal naive"), None)
    improvement = None
    if naive and naive["mape"] and best_mape:
        improvement = round((naive["mape"] - best_mape) / naive["mape"] * 100, 1)

    return {
        "has_data": True,
        "model": winner,
        "horizon_months": horizon_months,
        "historical": historical,
        "forecast": forecast,
        "band": "80%",
        "backtest": {
            "model": winner,
            "mape": best_mape,
            "mae": best.get("mae"),
            "rmse": best.get("rmse"),
            "holdout_months": best.get("holdout"),
            "candidates": results,
            "baseline_mape": naive["mape"] if naive else None,
            "improvement_vs_naive_pct": improvement,
        },
        "drivers": drivers,
        "category_forecast": category_forecast,
        "elasticity": elasticity,
        "gross_margin": gross_margin,
        "defaults": {
            "avg_discount_pct": round(avg_discount * 100, 1),
            "price_elasticity": elasticity["value"],
            "gross_margin_pct": round(gross_margin * 100, 1) if gross_margin else None,
        },
    }


def simulate_whatif(
    monthly_df: pd.DataFrame,
    price_change: float = 0,
    discount_change: float = 0,
    marketing_boost: float = 0,
    horizon_months: int = HORIZON_DEFAULT,
    base: Optional[Dict] = None,
) -> Dict:
    """
    Simulate the revenue and profit impact of pricing, discount and marketing changes.

    * price change: % change in list price
    * discount change: % change in the discount *level* (e.g. +20 → 15% becomes 18%)
    * marketing boost: % increase in marketing spend, with diminishing returns

    Revenue elasticity comes from the dataset (``elasticity``); profit uses the
    historical gross margin with unit costs held constant.
    """
    base = base or forecast_sales(monthly_df, horizon_months)

    if not base.get("has_data") or not base.get("forecast"):
        return {"error": "No data available", **base}

    elasticity = float(base.get("elasticity", {}).get("value", -1.2) or -1.2)
    avg_discount = float(base.get("defaults", {}).get("avg_discount_pct", 0.0)) / 100

    price_factor = max(1.0 + price_change / 100.0, 0.1)
    new_discount = min(max(avg_discount * (1 + discount_change / 100.0), 0.0), 0.9)
    discount_factor = (1 - new_discount) / (1 - avg_discount) if avg_discount < 1 else 1.0
    effective_price_factor = price_factor * discount_factor

    # Volume responds to the effective price; marketing adds volume with saturation.
    # Revenue scales with price * volume, i.e. price_factor^(1 + elasticity).
    volume_factor = effective_price_factor ** elasticity
    marketing_factor = 1 + 0.003 * marketing_boost / (1 + marketing_boost / 200.0)
    total_volume_factor = volume_factor * marketing_factor
    revenue_factor = (effective_price_factor ** (1 + elasticity)) * marketing_factor

    history = base.get("historical", [])
    if len(history) >= 12:
        last_12 = float(sum(item["value"] for item in history[-12:]))
        base_margin = float(
            np.mean([
                (item["value"] - item.get("profit", 0)) / item["value"]
                for item in history[-12:] if item["value"]
            ])
        ) if any("profit" in item for item in history[-12:]) else 0.0
    else:
        last_12 = float(sum(item["value"] for item in history))
        base_margin = 0.0

    # Gross margin from the forecast payload's dataset is attached by the router;
    # fall back to a 12% retail prior when it is missing.
    base_margin = float(base.get("gross_margin", base_margin or 0.12) or 0.12)
    cost_share = max(1 - base_margin, 0.05)

    base_forecast = base["forecast"]
    base_total = float(sum(item["value"] for item in base_forecast))

    adjusted = []
    for item in base_forecast:
        adjusted.append(
            {
                **item,
                "value": round(item["value"] * revenue_factor, 2),
                "lower": round(item["lower"] * revenue_factor, 2),
                "upper": round(item["upper"] * revenue_factor, 2),
            }
        )
    adjusted_total = float(sum(item["value"] for item in adjusted))

    # Revenue impact of each lever on its own (others held at zero).
    price_only = price_factor ** (1 + elasticity)
    discount_only = discount_factor ** (1 + elasticity)
    marketing_only = marketing_factor
    price_revenue = base_total * (price_only - 1)
    discount_revenue = base_total * (discount_only - 1)
    marketing_revenue = base_total * (marketing_only - 1)
    # The levers multiply, so the joint effect is not the sum of the individual
    # ones. Expose the remainder explicitly so the breakdown reconciles.
    interaction_revenue = (
        adjusted_total
        - base_total
        - price_revenue
        - discount_revenue
        - marketing_revenue
    )

    # Profit: revenue at the new price minus unit costs scaled by volume.
    base_profit = base_total * base_margin
    new_revenue = base_total * (effective_price_factor ** (1 + elasticity)) * marketing_factor
    new_cost = base_total * cost_share * total_volume_factor
    new_profit = new_revenue - new_cost
    profit_impact = new_profit - base_profit

    return {
        "historical": history,
        "base_forecast": base_forecast,
        "adjusted_forecast": adjusted,
        "base_total": round(base_total, 2),
        "adjusted_total": round(adjusted_total, 2),
        "impact_pct": round((adjusted_total - base_total) / base_total * 100, 2) if base_total else 0.0,
        "base_profit": round(base_profit, 2),
        "adjusted_profit": round(new_profit, 2),
        "profit_impact": round(profit_impact, 2),
        "profit_impact_pct": round(profit_impact / base_profit * 100, 2) if base_profit else 0.0,
        "breakdown": {
            "price": round(price_revenue, 2),
            "discount": round(discount_revenue, 2),
            "marketing": round(marketing_revenue, 2),
            "interaction": round(interaction_revenue, 2),
        },
        "assumptions": {
            "price_elasticity": elasticity,
            "avg_discount_pct": round(avg_discount * 100, 1),
            "new_discount_pct": round(new_discount * 100, 1),
            "gross_margin_pct": round(base_margin * 100, 1),
            "volume_factor": round(total_volume_factor, 4),
            "revenue_factor": round(revenue_factor, 4),
            "marketing_lift_pct": round((marketing_factor - 1) * 100, 2),
            "marketing_spend_not_deducted": marketing_boost > 0,
        },
        "model": base.get("model"),
        "horizon_months": horizon_months,
    }
