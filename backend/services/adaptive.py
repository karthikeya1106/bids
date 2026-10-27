"""
Adaptive analytics.

Chooses the analysis that the data actually supports and reports real metrics
from held-out data. Descriptive, predictive and causal language is kept
separate: correlations are labelled as associations, model scores come from a
holdout split, and unsupported tasks explain what is missing instead of
producing fabricated charts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

from services.profiling import coerce_datetime, coerce_numeric, detect_frequency
from services.semantics import looks_like_id

RANDOM_STATE = 42
MAX_MODEL_ROWS = 50_000
MAX_CLUSTER_ROWS = 5_000


# ─── Frame preparation ────────────────────────────────────────────────────────

def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce object columns that are mostly numbers or dates into real types."""
    work = df.copy()
    for column in work.columns:
        series = work[column]
        if series.dtype == object:
            numeric = coerce_numeric(series)
            if numeric.notna().mean() >= 0.9:
                work[column] = numeric
                continue
            if series.astype(str).str.contains(r"[-/:T]").mean() >= 0.8:
                parsed = coerce_datetime(series)
                if parsed.notna().mean() >= 0.85:
                    work[column] = parsed
    return work


def _is_identifier(column: str, series: pd.Series) -> bool:
    if looks_like_id(column):
        return True
    # Numeric columns are measures even when every value is distinct (revenue,
    # price, age); only text columns fall back to the uniqueness heuristic.
    if pd.api.types.is_numeric_dtype(series):
        return False
    non_null = series.dropna()
    return bool(len(non_null) and non_null.nunique() / len(non_null) > 0.97)


def feature_columns(
    df: pd.DataFrame,
    target: Optional[str],
    exclude: Optional[set[str]] = None,
) -> tuple[list[str], list[str]]:
    """Numeric and low-cardinality categorical predictors, leakage-guarded."""
    exclude = set(exclude or ())
    if target:
        exclude.add(target)
    exclude.add("__row__")

    numeric: list[str] = []
    categorical: list[str] = []
    for column in df.columns:
        if column in exclude:
            continue
        series = df[column]
        non_null = series.dropna()
        if non_null.empty or _is_identifier(column, series):
            continue
        if pd.api.types.is_numeric_dtype(series):
            if non_null.nunique() > 1:
                numeric.append(column)
        elif pd.api.types.is_datetime64_any_dtype(series):
            continue
        elif non_null.nunique() <= 20:
            categorical.append(column)
    return numeric[:25], categorical[:15]


def _model_frame(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) <= MAX_MODEL_ROWS:
        return df
    return df.sample(MAX_MODEL_ROWS, random_state=RANDOM_STATE).sort_index()


def _feature_importances(
    pipeline, numeric: list[str], categorical: list[str], preprocessor, limit: int = 10
) -> list[dict]:
    model = pipeline.named_steps["model"]
    try:
        names = list(preprocessor.get_feature_names_out())
    except Exception:
        return []

    if hasattr(model, "feature_importances_"):
        values = model.feature_importances_
    elif hasattr(model, "coef_"):
        coef = np.asarray(model.coef_)
        values = np.abs(coef).mean(axis=0) if coef.ndim > 1 else np.abs(coef)
    else:
        return []

    if len(values) != len(names):
        return []

    aggregated: dict[str, float] = {}
    for name, value in zip(names, values):
        base = name.split("__", 1)[-1]
        source = base
        for candidate in sorted(numeric + categorical, key=len, reverse=True):
            if base == candidate or base.startswith(candidate + "_"):
                source = candidate
                break
        aggregated[source] = aggregated.get(source, 0.0) + float(value)

    total = sum(aggregated.values()) or 1.0
    return [
        {"feature": feature, "importance": round(value / total, 4)}
        for feature, value in sorted(aggregated.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _safe_metric(value: Any, digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(number) or np.isinf(number):
        return None
    return round(number, digits)


# ─── EDA ──────────────────────────────────────────────────────────────────────

def exploratory_summary(df: pd.DataFrame, profile: dict) -> dict:
    work = prepare_frame(df)
    numeric_rows: list[dict] = []
    categorical_rows: list[dict] = []
    datetime_rows: list[dict] = []

    for column in work.columns:
        series = work[column]
        non_null = series.dropna()
        if non_null.empty:
            continue
        if pd.api.types.is_numeric_dtype(series) and non_null.nunique() > 2:
            numeric_rows.append({
                "column": column,
                "count": int(non_null.size),
                "mean": _safe_metric(non_null.mean(), 2),
                "median": _safe_metric(non_null.median(), 2),
                "std": _safe_metric(non_null.std(), 2),
                "min": _safe_metric(non_null.min(), 2),
                "max": _safe_metric(non_null.max(), 2),
                "missing_pct": round(float(series.isna().mean() * 100), 1),
            })
        elif pd.api.types.is_datetime64_any_dtype(series):
            coverage = detect_frequency(series)
            datetime_rows.append({
                "column": column,
                **(coverage or {}),
                "missing_pct": round(float(series.isna().mean() * 100), 1),
            })
        elif non_null.nunique() <= 50:
            counts = non_null.astype(str).value_counts().head(6)
            total = int(non_null.size)
            categorical_rows.append({
                "column": column,
                "unique": int(non_null.nunique()),
                "missing_pct": round(float(series.isna().mean() * 100), 1),
                "top": [
                    {"value": str(value)[:80], "count": int(count), "share": round(count / total * 100, 1)}
                    for value, count in counts.items()
                ],
            })

    return {
        "numeric": sorted(numeric_rows, key=lambda row: row["column"])[:12],
        "categorical": sorted(categorical_rows, key=lambda row: row["unique"])[:10],
        "datetime": datetime_rows[:4],
        "correlations": profile.get("correlations", []),
        "quality": profile.get("quality", []),
    }


# ─── Classification ───────────────────────────────────────────────────────────

def classify(
    df: pd.DataFrame,
    target: str,
    numeric: list[str],
    categorical: list[str],
    event_label: Optional[str] = None,
) -> dict:
    from sklearn.compose import ColumnTransformer
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        balanced_accuracy_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    work = _model_frame(df)
    y = work[target].astype(str).str.strip()
    classes = sorted(y.unique().tolist())
    counts = y.value_counts()

    result: dict[str, Any] = {
        "type": "classification",
        "target": target,
        "classes": classes,
        "class_distribution": [
            {"label": label, "count": int(counts.get(label, 0)), "share": round(int(counts.get(label, 0)) / len(y) * 100, 1)}
            for label in classes
        ],
        "features": {"numeric": numeric, "categorical": categorical},
        "metrics": {},
        "baseline": {},
        "confusion": {"labels": classes, "matrix": []},
        "importances": [],
        "probability_bands": [],
        "notes": [],
        "method": "",
    }

    if not numeric and not categorical:
        result["notes"].append("No usable predictors remained after removing identifiers and the target.")
        result["available"] = False
        return result
    if len(classes) < 2:
        result["notes"].append("The target has a single class, so no classifier can be trained.")
        result["available"] = False
        return result
    if len(y) < 30 or counts.min() < 2:
        result["notes"].append(
            f"Not enough labelled rows to hold out a test set ({len(y)} rows, smallest class {int(counts.min())})."
        )
        result["available"] = False
        return result

    X = work[numeric + categorical]
    stratify = y if counts.min() >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_STATE, stratify=stratify
    )

    preprocessor = ColumnTransformer(
        [
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric),
            (
                "cat",
                Pipeline([
                    ("impute", SimpleImputer(strategy="most_frequent")),
                    ("encode", OneHotEncoder(handle_unknown="ignore", max_categories=25)),
                ]),
                categorical,
            ),
        ],
        remainder="drop",
    )

    # Model selection is capped on large files so a page request stays usable;
    # the chosen model is still refitted on the full training split.
    max_cv_rows = 8000
    if len(X_train) > max_cv_rows:
        cv_frame = X_train.sample(max_cv_rows, random_state=RANDOM_STATE)
        X_cv, y_cv = cv_frame, y_train.loc[cv_frame.index]
    else:
        X_cv, y_cv = X_train, y_train

    trees = 150 if len(work) <= 20_000 else 90
    candidates = {
        "Logistic regression": LogisticRegression(max_iter=1000, class_weight="balanced"),
        "Random forest": RandomForestClassifier(
            n_estimators=trees, min_samples_leaf=3, class_weight="balanced_subsample",
            random_state=RANDOM_STATE, n_jobs=-1,
        ),
    }

    min_class = int(y_cv.value_counts().min())
    cv_splits = min(5, min_class) if min_class >= 2 else 0
    comparison = []
    best_name, best_pipeline, best_score = "", None, -1.0
    for name, model in candidates.items():
        pipeline = Pipeline([("prep", preprocessor), ("model", model)])
        try:
            if cv_splits >= 2:
                cv = StratifiedKFold(n_splits=cv_splits, shuffle=True, random_state=RANDOM_STATE)
                scores = cross_val_score(pipeline, X_cv, y_cv, cv=cv, scoring="f1_macro")
                score = float(np.mean(scores))
                std = float(np.std(scores))
            else:
                score, std = float("nan"), float("nan")
        except Exception as exc:  # pragma: no cover - defensive
            comparison.append({"model": name, "cv_f1_macro": None, "error": str(exc)})
            continue
        comparison.append({
            "model": name,
            "cv_f1_macro": _safe_metric(score),
            "cv_std": _safe_metric(std),
        })
        if np.isfinite(score) and score > best_score:
            best_name, best_pipeline, best_score = name, pipeline, score

    if best_pipeline is None:
        # Cross-validation unavailable (tiny classes) — fall back to the forest.
        best_name = "Random forest"
        best_pipeline = Pipeline([("prep", preprocessor), ("model", candidates["Random forest"])])
    best_pipeline.fit(X_train, y_train)
    predictions = best_pipeline.predict(X_test)
    probabilities = None
    try:
        probabilities = best_pipeline.predict_proba(X_test)
    except Exception:
        probabilities = None

    baseline = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
    baseline_predictions = baseline.predict(X_test)

    labels = classes
    matrix = confusion_matrix(y_test, predictions, labels=labels)

    roc_auc = None
    if len(classes) == 2 and probabilities is not None and len(np.unique(y_test)) == 2:
        positive = classes[1]
        try:
            roc_auc = roc_auc_score((y_test == positive).astype(int), probabilities[:, 1])
        except Exception:
            roc_auc = None

    positive_label = event_label if event_label in classes else classes[-1]
    probability_bands: list[dict] = []
    if probabilities is not None and len(classes) == 2:
        positive_index = classes.index(positive_label)
        scores = probabilities[:, positive_index]
        observed = (y_test == positive_label).to_numpy().astype(int)
        edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0001]
        for index in range(len(edges) - 1):
            lower, upper = edges[index], edges[index + 1]
            mask_band = (scores >= lower) & (scores < upper)
            selected = int(mask_band.sum())
            if not selected:
                continue
            probability_bands.append({
                "band": f"{int(lower * 100)}–{min(100, int(upper * 100))}%",
                "count": selected,
                "observed_rate": round(float(observed[mask_band].mean() * 100), 1),
            })

    result.update({
        "available": True,
        "positive_class": positive_label,
        "probability_bands": probability_bands,
        "method": f"{best_name} on a stratified 75/25 holdout",
        "metrics": {
            "accuracy": _safe_metric(accuracy_score(y_test, predictions)),
            "balanced_accuracy": _safe_metric(balanced_accuracy_score(y_test, predictions)),
            "precision_weighted": _safe_metric(precision_score(y_test, predictions, average="weighted", zero_division=0)),
            "recall_weighted": _safe_metric(recall_score(y_test, predictions, average="weighted", zero_division=0)),
            "f1_weighted": _safe_metric(f1_score(y_test, predictions, average="weighted", zero_division=0)),
            "f1_macro": _safe_metric(f1_score(y_test, predictions, average="macro", zero_division=0)),
            "roc_auc": _safe_metric(roc_auc),
        },
        "baseline": {
            "model": "Most-frequent class",
            "accuracy": _safe_metric(accuracy_score(y_test, baseline_predictions)),
            "f1_macro": _safe_metric(f1_score(y_test, baseline_predictions, average="macro", zero_division=0)),
        },
        "confusion": {"labels": labels, "matrix": matrix.astype(int).tolist()},
        "comparison": comparison,
        "split": {
            "train_rows": int(len(X_train)),
            "test_rows": int(len(X_test)),
            "stratified": stratify is not None,
            "cv_rows": int(len(X_cv)),
        },
        "selected_model": best_name,
        "importances": _feature_importances(best_pipeline, numeric, categorical, best_pipeline.named_steps["prep"]),
        "notes": [
            "Scores are measured on rows the model never saw during training.",
            "Feature importance shows association, not a causal effect.",
        ],
    })

    if len(X_cv) < len(X_train):
        result["notes"].append(
            f"Model comparison used a {len(X_cv):,}-row sample of the training split for speed; "
            "the selected model was refitted on all training rows."
        )
    if counts.min() / len(y) < 0.15:
        result["notes"].append(
            f"Class imbalance: the smallest class is {counts.min() / len(y) * 100:.1f}% of rows; "
            "balanced accuracy and macro-F1 are the fairer metrics."
        )
    if roc_auc is None and len(classes) == 2:
        result["notes"].append("ROC-AUC unavailable because the test split lacks one of the classes.")
    return result


# ─── Regression ───────────────────────────────────────────────────────────────

def regress(
    df: pd.DataFrame,
    target: str,
    numeric: list[str],
    categorical: list[str],
) -> dict:
    from sklearn.compose import ColumnTransformer
    from sklearn.dummy import DummyRegressor
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
    from sklearn.model_selection import KFold, cross_val_score, train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    work = _model_frame(df)
    y = coerce_numeric(work[target])
    valid = y.notna()
    work = work[valid]
    y = y[valid]

    result: dict[str, Any] = {
        "type": "regression",
        "target": target,
        "features": {"numeric": numeric, "categorical": categorical},
        "metrics": {},
        "baseline": {},
        "importances": [],
        "notes": [],
        "method": "",
    }

    if not numeric and not categorical:
        result.update({"available": False, "notes": ["No usable predictors after removing identifiers and the target."]})
        return result
    if len(y) < 30 or y.std() == 0:
        result.update({
            "available": False,
            "notes": [f"Regression needs at least 30 rows and a target with variance ({len(y)} rows available)."],
        })
        return result

    X = work[numeric + categorical]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_STATE
    )

    preprocessor = ColumnTransformer(
        [
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric),
            (
                "cat",
                Pipeline([
                    ("impute", SimpleImputer(strategy="most_frequent")),
                    ("encode", OneHotEncoder(handle_unknown="ignore", max_categories=25)),
                ]),
                categorical,
            ),
        ],
        remainder="drop",
    )

    max_cv_rows = 8000
    if len(X_train) > max_cv_rows:
        cv_frame = X_train.sample(max_cv_rows, random_state=RANDOM_STATE)
        X_cv, y_cv = cv_frame, y_train.loc[cv_frame.index]
    else:
        X_cv, y_cv = X_train, y_train

    candidates = {
        "Linear regression": LinearRegression(),
        "Random forest regressor": RandomForestRegressor(
            n_estimators=150 if len(work) <= 20_000 else 90,
            min_samples_leaf=3, random_state=RANDOM_STATE, n_jobs=-1,
        ),
    }
    comparison = []
    best_name, best_pipeline, best_score = "", None, np.inf
    cv = KFold(n_splits=min(5, max(2, len(y_cv) // 20)), shuffle=True, random_state=RANDOM_STATE)
    for name, model in candidates.items():
        pipeline = Pipeline([("prep", preprocessor), ("model", model)])
        try:
            scores = cross_val_score(
                pipeline, X_cv, y_cv, cv=cv, scoring="neg_mean_absolute_error"
            )
            mae = float(-np.mean(scores))
        except Exception as exc:  # pragma: no cover - defensive
            comparison.append({"model": name, "cv_mae": None, "error": str(exc)})
            continue
        comparison.append({"model": name, "cv_mae": _safe_metric(mae, 2)})
        if mae < best_score:
            best_name, best_pipeline, best_score = name, pipeline, mae

    if best_pipeline is None:
        best_name = "Random forest regressor"
        best_pipeline = Pipeline([("prep", preprocessor), ("model", candidates["Random forest regressor"])])

    best_pipeline.fit(X_train, y_train)
    predictions = best_pipeline.predict(X_test)
    baseline = DummyRegressor(strategy="mean").fit(X_train, y_train)
    baseline_predictions = baseline.predict(X_test)

    mape = None
    mask = y_test != 0
    if mask.sum() >= 5:
        mape = float(np.mean(np.abs((y_test[mask] - predictions[mask]) / y_test[mask])) * 100)

    result.update({
        "available": True,
        "method": f"{best_name} on a 75/25 holdout",
        "metrics": {
            "mae": _safe_metric(mean_absolute_error(y_test, predictions), 2),
            "rmse": _safe_metric(root_mean_squared_error(y_test, predictions), 2),
            "r2": _safe_metric(r2_score(y_test, predictions), 4),
            "mape": _safe_metric(mape, 2),
        },
        "baseline": {
            "model": "Predict the mean",
            "mae": _safe_metric(mean_absolute_error(y_test, baseline_predictions), 2),
            "r2": _safe_metric(r2_score(y_test, baseline_predictions), 4),
        },
        "comparison": comparison,
        "selected_model": best_name,
        "split": {
            "train_rows": int(len(X_train)),
            "test_rows": int(len(X_test)),
            "cv_rows": int(len(X_cv)),
        },
        "target_stats": {
            "mean": _safe_metric(y.mean(), 2),
            "min": _safe_metric(y.min(), 2),
            "max": _safe_metric(y.max(), 2),
        },
        "importances": _feature_importances(best_pipeline, numeric, categorical, best_pipeline.named_steps["prep"]),
        "notes": [
            "Scores are measured on held-out rows.",
            "R² below 0 means the model is worse than always predicting the mean.",
        ],
    })
    if result["metrics"].get("r2") is not None and result["metrics"]["r2"] < 0:
        result["notes"].append("The model did not beat the mean baseline; treat predictions as unreliable.")
    return result


# ─── Clustering ───────────────────────────────────────────────────────────────

def cluster(
    df: pd.DataFrame,
    numeric: list[str],
    target: Optional[str] = None,
    outcome: Optional[pd.Series] = None,
    outcome_name: str = "outcome",
) -> dict:
    """K-means segments plus the observed outcome rate per segment (when given)."""
    from sklearn.cluster import KMeans
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import silhouette_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    work = df
    if len(work) > MAX_CLUSTER_ROWS:
        work = work.sample(MAX_CLUSTER_ROWS, random_state=RANDOM_STATE)
    features = [column for column in numeric if column != target][:10]
    if outcome is not None:
        outcome = outcome.reindex(work.index)

    result: dict[str, Any] = {
        "type": "clustering",
        "features": features,
        "outcome_name": outcome_name,
        "clusters": [],
        "notes": [],
        "method": "K-means on standardised numeric features",
    }

    if len(features) < 2 or len(work) < 30:
        result.update({
            "available": False,
            "notes": ["Clustering needs at least 30 rows and 2 numeric features."],
        })
        return result

    X = work[features]

    best_k, best_score, best_labels = 3, -1.0, None
    for k in range(2, min(6, max(3, len(X) // 20))):
        candidate = Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE)),
        ])
        try:
            labels = candidate.fit_predict(X)
            if len(set(labels)) < 2:
                continue
            scaled = candidate[:-1].transform(X)
            score = float(silhouette_score(scaled, labels))
        except Exception:
            continue
        if score > best_score:
            best_k, best_score, best_labels = k, score, labels

    if best_labels is None:
        result.update({"available": False, "notes": ["Clustering could not separate the data into stable groups."]})
        return result

    scored = work.copy()
    scored["cluster"] = best_labels
    global_means = scored[features].mean()
    global_std = scored[features].std().replace(0, 1)
    cluster_rows = []
    for cluster_id in sorted(scored["cluster"].unique()):
        group = scored[scored["cluster"] == cluster_id]
        z_scores = ((group[features].mean() - global_means) / global_std).sort_values(ascending=False)
        top = [name for name in z_scores.index[:3]]
        outcome_rate = None
        if outcome is not None:
            group_outcome = outcome.loc[group.index].dropna()
            if len(group_outcome):
                outcome_rate = round(float(group_outcome.mean() * 100), 1)
        cluster_rows.append({
            "cluster": int(cluster_id),
            "size": int(len(group)),
            "share": round(len(group) / len(scored) * 100, 1),
            "outcome_rate": outcome_rate,
            "means": {column: _safe_metric(group[column].mean(), 2) for column in features},
            "distinguishing": [
                {"feature": column, "z": _safe_metric((group[column].mean() - global_means[column]) / global_std[column], 2)}
                for column in top
            ],
            "description": "above average " + ", ".join(top),
        })

    result.update({
        "available": True,
        "k": best_k,
        "silhouette": _safe_metric(best_score, 3),
        "rows_used": int(len(scored)),
        "clusters": cluster_rows,
        "notes": [
            "K-means with k chosen by silhouette score; segments are descriptive, not predictive.",
            "Silhouette near 0 means the groups overlap heavily.",
        ],
    })
    return result


# ─── Forecasting ──────────────────────────────────────────────────────────────

def _period_format(frequency: str) -> tuple[str, str]:
    if frequency in {"monthly", "quarterly", "yearly"}:
        return "M", "%Y-%m"
    if frequency == "weekly":
        return "W", "%Y-%m-%d"
    return "D", "%Y-%m-%d"


def forecast(
    df: pd.DataFrame,
    time_column: str,
    target: str,
) -> dict:
    work = pd.DataFrame({
        "date": coerce_datetime(df[time_column]),
        "value": coerce_numeric(df[target]),
    }).dropna()

    result: dict[str, Any] = {
        "type": "forecast",
        "time_column": time_column,
        "target": target,
        "history": [],
        "forecast": [],
        "metrics": {},
        "notes": [],
    }

    if len(work) < 12:
        result.update({"available": False, "notes": ["Forecasting needs at least 12 dated observations."]})
        return result

    coverage = detect_frequency(work["date"])
    frequency = coverage.get("frequency", "monthly") if coverage else "monthly"
    rule, date_format = _period_format(frequency)
    if frequency in {"daily", "2-3 days"} and coverage and coverage["span_days"] > 180:
        rule, date_format = "M", "%Y-%m"

    series = (
        work.set_index("date")
        .sort_index()
        .assign(value=lambda frame: frame["value"])
        .resample(rule)["value"]
        .sum(min_count=1)
        .dropna()
    )

    if len(series) < 8:
        result.update({
            "available": False,
            "notes": [
                f"Only {len(series)} complete periods after aggregation; at least 8 are needed for a reliable holdout."
            ],
        })
        return result
    if series.std() == 0:
        result.update({"available": False, "notes": ["The series is constant, so there is nothing to forecast."]})
        return result

    holdout = min(6, max(3, len(series) // 4))
    train, test = series.iloc[:-holdout], series.iloc[-holdout:]
    values = train.to_numpy(dtype=float)

    method = "Holt damped trend"
    predictions: np.ndarray
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        fitted = ExponentialSmoothing(
            values,
            trend="add",
            damped_trend=True,
            initialization_method="estimated",
        ).fit()
        predictions = np.asarray(fitted.forecast(holdout), dtype=float)
    except Exception:
        # Deterministic fallback: linear trend fitted on the training window.
        method = "Linear trend (fallback)"
        x = np.arange(len(values))
        slope, intercept = np.polyfit(x, values, 1)
        predictions = slope * np.arange(len(values), len(values) + holdout) + intercept

    naive = np.repeat(values[-1], holdout)
    mae = float(np.mean(np.abs(test.to_numpy() - predictions)))
    naive_mae = float(np.mean(np.abs(test.to_numpy() - naive)))
    if naive_mae < mae:
        method = "Seasonal naïve (baseline won the holdout)"
        predictions = naive
        mae = naive_mae

    rmse = float(np.sqrt(np.mean((test.to_numpy() - predictions) ** 2)))
    non_zero = test.to_numpy() != 0
    mape = (
        float(np.mean(np.abs((test.to_numpy()[non_zero] - predictions[non_zero]) / test.to_numpy()[non_zero])) * 100)
        if non_zero.any() else None
    )

    horizon = 6
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        final_fit = ExponentialSmoothing(
            series.to_numpy(dtype=float),
            trend="add",
            damped_trend=True,
            initialization_method="estimated",
        ).fit()
        future = np.asarray(final_fit.forecast(horizon), dtype=float)
    except Exception:
        x = np.arange(len(series))
        slope, intercept = np.polyfit(x, series.to_numpy(dtype=float), 1)
        future = slope * np.arange(len(series), len(series) + horizon) + intercept

    residual_std = float(np.std(test.to_numpy() - predictions, ddof=1)) if holdout > 2 else float(series.std())
    last_period = series.index[-1]
    future_index = pd.date_range(last_period + pd.tseries.frequencies.to_offset(rule), periods=horizon, freq=rule)

    history = [
        {"period": index.strftime(date_format), "value": _safe_metric(value, 2)}
        for index, value in series.items()
    ]
    forecast_rows = []
    for step, (index, value) in enumerate(zip(future_index, future), start=1):
        spread = 1.96 * residual_std * float(np.sqrt(step))
        forecast_rows.append({
            "period": index.strftime(date_format),
            "value": _safe_metric(value, 2),
            "lower": _safe_metric(value - spread, 2),
            "upper": _safe_metric(value + spread, 2),
        })

    result.update({
        "available": True,
        "method": method,
        "frequency": rule,
        "history": history[-24:],
        "forecast": forecast_rows,
        "metrics": {
            "holdout_periods": holdout,
            "mae": _safe_metric(mae, 2),
            "rmse": _safe_metric(rmse, 2),
            "mape": _safe_metric(mape, 2),
            "naive_mae": _safe_metric(naive_mae, 2),
        },
        "notes": [
            f"Trained on {len(train)} periods and validated on the last {holdout} periods.",
            "Intervals widen with the horizon and assume the recent pattern continues.",
            "Aggregated by period; individual transactions are not predicted.",
        ],
    })
    if mape is not None and mape > 25:
        result["notes"].append(f"Holdout error is {mape:.0f}%; treat the projection as indicative only.")
    return result


# ─── Orchestration ────────────────────────────────────────────────────────────

def build_adaptive_report(
    df: pd.DataFrame,
    profile: dict,
    schema_id: str,
    task: str,
    target: Optional[str],
    validation: Optional[dict] = None,
) -> dict:
    """Produce the dataset-specific report, running only supported analyses."""
    work = prepare_frame(df)
    validation = validation or {}
    supported = {
        "eda": True,
        "clustering": len(work) >= 30,
        "classification": False,
        "regression": False,
        "forecast": bool((validation.get("forecast") or {}).get("available")),
    }

    task_result: Optional[dict] = None
    notes: list[str] = []

    numeric, categorical = feature_columns(work, target)
    if task == "classification" and target and target in work.columns:
        task_result = classify(work, target, numeric, categorical)
        supported["classification"] = bool(task_result.get("available"))
    elif task == "regression" and target and target in work.columns:
        task_result = regress(work, target, numeric, categorical)
        supported["regression"] = bool(task_result.get("available"))
    elif task == "clustering":
        task_result = cluster(work, numeric, target)
        supported["clustering"] = bool(task_result.get("available"))
    elif task == "forecast":
        forecast_info = validation.get("forecast") or {}
        time_column = forecast_info.get("time_column")
        forecast_target = target or forecast_info.get("target")
        if not time_column or time_column not in work.columns:
            time_column = next(
                (column for column in work.columns if pd.api.types.is_datetime64_any_dtype(work[column])),
                None,
            )
        if forecast_target and forecast_target not in work.columns:
            forecast_target = None
        if not forecast_target and numeric:
            forecast_target = numeric[0]
        if time_column and forecast_target:
            task_result = forecast(work, time_column, forecast_target)
            supported["forecast"] = bool(task_result.get("available"))
        else:
            task_result = {
                "type": "forecast",
                "available": False,
                "notes": ["No date column and numeric measure combination was found."],
            }
            supported["forecast"] = False

    if task_result and not task_result.get("available", True):
        notes.extend(task_result.get("notes", []))
        task_result = None

    if task_result is None and task not in ("eda",):
        notes.append(f"The requested '{task}' analysis could not run on this dataset; profiling and EDA are shown instead.")

    # Always offer clustering as an exploratory extra when it is safe, so an
    # unlabelled dataset still gets more than univariate summaries.
    extra_clusters = None
    if task != "clustering" and len(work) >= 60 and len(numeric) >= 2:
        candidate = cluster(work, numeric, target)
        if candidate.get("available"):
            extra_clusters = candidate

    limitations = [
        "Results describe this file only; they are not an external validation.",
        "Associations and feature importance are not proof of causation.",
        "Rows with unusable required values were excluded at ingestion.",
    ]
    for check in validation.get("checks", []):
        if check.get("status") == "warn":
            limitations.append(f"{check['label']}: {check['detail']}")
    limitations.extend(notes)
    if len(work) > MAX_MODEL_ROWS:
        limitations.append(f"Modelling used a {MAX_MODEL_ROWS:,}-row sample for speed.")

    type_counts = profile.get("type_counts", {}) or {}
    summary = {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "numeric_columns": int(type_counts.get("numeric", 0)),
        "categorical_columns": int(type_counts.get("categorical", 0)),
        "missing_pct": profile.get("missing_pct", 0),
        "duplicate_rows": profile.get("duplicate_rows", 0),
        "time_coverage": profile.get("time_coverage"),
        "target": target,
        "task": task,
    }

    return {
        "mode": "adaptive",
        "schema": schema_id,
        "summary": summary,
        "eda": exploratory_summary(df, profile),
        "task": task_result,
        "clusters": extra_clusters,
        "supported_tasks": supported,
        "limitations": limitations[:12],
        "generated_at": datetime.utcnow().isoformat(),
    }
