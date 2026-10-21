"""
Sales & Demand Forecasting using XGBoost with time-series feature engineering.
Falls back to trend extrapolation if XGBoost training data is insufficient.
"""
import pandas as pd
import numpy as np
from datetime import date, timedelta
from typing import List, Dict


def create_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["month"] = df["ds"].dt.month
    df["quarter"] = df["ds"].dt.quarter
    df["year"] = df["ds"].dt.year
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    for lag in [1, 2, 3, 6, 12]:
        df[f"lag_{lag}"] = df["y"].shift(lag)
    df["rolling_3"] = df["y"].shift(1).rolling(3).mean()
    df["rolling_6"] = df["y"].shift(1).rolling(6).mean()
    return df.dropna()


def forecast_sales(monthly_df: pd.DataFrame, horizon_months: int = 6) -> Dict:
    """
    monthly_df: DataFrame with columns [ds (datetime), y (sales)]
    Returns forecast with confidence intervals.
    """
    try:
        from xgboost import XGBRegressor

        df = monthly_df[["ds", "y"]].copy().sort_values("ds").reset_index(drop=True)
        feature_df = create_features(df)

        if len(feature_df) < 8:
            return _arima_fallback(monthly_df, horizon_months)

        feature_cols = ["month", "quarter", "year", "month_sin", "month_cos",
                        "lag_1", "lag_2", "lag_3", "lag_6", "rolling_3", "rolling_6"]
        feature_cols = [c for c in feature_cols if c in feature_df.columns]

        X = feature_df[feature_cols]
        y = feature_df["y"]

        model = XGBRegressor(n_estimators=200, learning_rate=0.05, max_depth=4,
                             subsample=0.8, random_state=42, verbosity=0)
        model.fit(X, y)

        # Generate future dates
        last_date = df["ds"].max()
        future_dates = [last_date + pd.DateOffset(months=i + 1) for i in range(horizon_months)]
        future_df = pd.DataFrame({"ds": future_dates, "y": np.nan})
        combined = pd.concat([df, future_df], ignore_index=True)

        # Iterative forecast
        for i in range(len(df), len(combined)):
            feat = create_features(combined.iloc[: i + 1])
            if len(feat) == 0:
                combined.at[i, "y"] = df["y"].mean()
                continue
            row = feat.iloc[-1][feature_cols]
            pred = model.predict(row.values.reshape(1, -1))[0]
            combined.at[i, "y"] = max(pred, 0)

        forecast_vals = combined.tail(horizon_months)["y"].tolist()
        std = df["y"].std()
        if pd.isna(std) or std == 0:
            std = df["y"].mean() * 0.1  # fallback: 10% of mean

    except Exception:
        return _arima_fallback(monthly_df, horizon_months)

    historical = [{"date": str(r["ds"])[:7], "value": round(r["y"], 2)} for _, r in monthly_df.iterrows()]
    forecast = [
        {
            "date": str(future_dates[i])[:7],
            "value": round(forecast_vals[i], 2),
            "lower": round(max(forecast_vals[i] - 1.5 * std, 0), 2),
            "upper": round(forecast_vals[i] + 1.5 * std, 2),
        }
        for i in range(horizon_months)
    ]

    return {"historical": historical, "forecast": forecast, "model": "XGBoost"}


def _arima_fallback(monthly_df: pd.DataFrame, horizon: int) -> Dict:
    """Simple linear trend extrapolation fallback."""
    df = monthly_df.reset_index(drop=True)
    y = df["y"].values
    x = np.arange(len(y))
    coeffs = np.polyfit(x, y, 1)
    trend_fn = np.poly1d(coeffs)

    std = np.std(y)
    if std == 0:
        std = np.mean(y) * 0.1  # fallback: 10% of mean

    historical = [
        {"date": str(df.loc[i, "ds"])[:7], "value": round(float(y[i]), 2)}
        for i in range(len(df))
    ]

    last_date = df["ds"].max()
    forecast = []
    for i in range(1, horizon + 1):
        pred = float(max(trend_fn(len(y) + i - 1), 0))
        fut_date = last_date + pd.DateOffset(months=i)
        forecast.append({
            "date": str(fut_date)[:7],
            "value": round(pred, 2),
            "lower": round(max(pred - 1.5 * std, 0), 2),
            "upper": round(pred + 1.5 * std, 2),
        })

    return {"historical": historical, "forecast": forecast, "model": "Trend Extrapolation"}


def simulate_whatif(monthly_df: pd.DataFrame, price_change: float = 0,
                    discount_change: float = 0, marketing_boost: float = 0) -> Dict:
    """
    Simulate impact of parameter changes on forecast.
    price_change: % change in price (-50 to +50)
    discount_change: % change in discount level (-20 to +20)
    marketing_boost: % boost in marketing spend (0 to +100)
    """
    base = forecast_sales(monthly_df)
    multiplier = 1.0
    multiplier += marketing_boost * 0.003       # 1% marketing ≈ 0.3% sales lift
    multiplier -= price_change * 0.008          # 1% price increase → -0.8% demand (elasticity)
    multiplier += discount_change * 0.004       # 1% more discount → +0.4% conversion

    multiplier = max(multiplier, 0.01)  # prevent negative multiplier

    adjusted_forecast = [
        {**f, "value": round(f["value"] * multiplier, 2),
         "lower": round(f["lower"] * multiplier, 2),
         "upper": round(f["upper"] * multiplier, 2)}
        for f in base["forecast"]
    ]

    base_total = sum(f["value"] for f in base["forecast"])
    adj_total = sum(f["value"] for f in adjusted_forecast)

    return {
        "base_forecast": base["forecast"],
        "adjusted_forecast": adjusted_forecast,
        "historical": base["historical"],
        "impact_pct": round((adj_total - base_total) / max(base_total, 1) * 100, 2),
        "base_total": round(base_total, 2),
        "adjusted_total": round(adj_total, 2),
        "model": base["model"],
    }
