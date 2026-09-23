"""Global gradient-boosting challenger for regular-SKU demand forecasts."""

from typing import Iterable, List

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from .forecast import seasonal_indices, supplier_seasonal_indices


KEYS = ["sku_code", "supplier"]
DEMAND_FEATURES = [
    "demand_lag_0",
    "demand_lag_1",
    "demand_lag_2",
    "demand_lag_5",
    "demand_lag_11",
    "rolling_mean_3",
    "rolling_mean_6",
    "same_month_last_year",
]
FEATURE_COLUMNS = [
    *DEMAND_FEATURES,
    "sku_season",
    "supplier_season",
    "growth_yoy",
    "zero_share_12",
    "stockout_months_12",
    "target_month",
    "horizon",
    "supplier_feature",
    "category_feature",
]
CATEGORICAL_FEATURES = [
    FEATURE_COLUMNS.index("supplier_feature"),
    FEATURE_COLUMNS.index("category_feature"),
    FEATURE_COLUMNS.index("target_month"),
]


def _regular_history(
    demand: pd.DataFrame, segments: pd.DataFrame
) -> pd.DataFrame:
    regular = segments.loc[segments["segment"].eq("regular"), KEYS]
    frame = demand.merge(regular, on=KEYS, how="inner").copy()
    frame["period"] = pd.PeriodIndex(frame["month"], freq="M")
    frame["demand"] = pd.to_numeric(frame["demand"], errors="coerce").fillna(0.0)
    if "is_stockout" not in frame:
        frame["is_stockout"] = False
    frame["is_stockout"] = frame["is_stockout"].fillna(False).astype(bool)
    return (
        frame.groupby([*KEYS, "period"], as_index=False)
        .agg(demand=("demand", "sum"), is_stockout=("is_stockout", "max"))
        .sort_values([*KEYS, "period"])
    )


def _category_mapping(sku_ref: pd.DataFrame) -> dict[str, int]:
    categories = sorted(
        sku_ref["category"].fillna("без категории").astype(str).unique()
    )
    return {category: index for index, category in enumerate(categories)}


def _feature_rows(
    history: pd.DataFrame,
    sku_ref: pd.DataFrame,
    origin: pd.Period,
    horizons: Iterable[int],
) -> List[dict[str, object]]:
    origin = pd.Period(origin, freq="M")
    available = history.loc[history["period"].le(origin)].copy()
    seasonal_source = available.assign(month=available["period"].astype(str))
    sku_seasons = seasonal_indices(seasonal_source)
    supplier_seasons = supplier_seasonal_indices(seasonal_source, "demand")
    sku_season_map = sku_seasons.set_index([*KEYS, "month_num"])[
        "seasonal_index"
    ].to_dict()
    supplier_season_map = supplier_seasons.set_index(
        ["supplier", "month_num"]
    )["supplier_season"].to_dict()

    references = sku_ref.set_index(KEYS)
    category_codes = _category_mapping(sku_ref)
    supplier_codes = {
        supplier: index
        for index, supplier in enumerate(sorted(history["supplier"].unique()))
    }
    rows: List[dict[str, object]] = []
    horizon_values = tuple(int(value) for value in horizons)
    history_months = [origin - offset for offset in range(11, -1, -1)]
    recent_months = [origin - offset for offset in range(2, -1, -1)]
    prior_year_months = [month - 12 for month in recent_months]

    for key, sku_frame in available.groupby(KEYS, sort=False):
        sku_code, supplier = key
        demand_map = sku_frame.set_index("period")["demand"].to_dict()
        stockout_map = sku_frame.set_index("period")["is_stockout"].to_dict()
        trailing = np.array(
            [float(demand_map.get(month, 0.0)) for month in history_months]
        )
        base = float(trailing.mean() + 1.0)
        recent = sum(float(demand_map.get(month, 0.0)) for month in recent_months)
        prior = sum(
            float(demand_map.get(month, 0.0)) for month in prior_year_months
        )
        growth = 1.0 if prior == 0 else recent / prior
        growth = float(np.clip(growth, 0.5, 2.0))
        category = str(references.loc[key, "category"])

        for horizon in horizon_values:
            target = origin + horizon
            values = {
                "demand_lag_0": float(demand_map.get(origin, 0.0)) / base,
                "demand_lag_1": float(demand_map.get(origin - 1, 0.0)) / base,
                "demand_lag_2": float(demand_map.get(origin - 2, 0.0)) / base,
                "demand_lag_5": float(demand_map.get(origin - 5, 0.0)) / base,
                "demand_lag_11": float(demand_map.get(origin - 11, 0.0)) / base,
                "rolling_mean_3": float(trailing[-3:].mean()) / base,
                "rolling_mean_6": float(trailing[-6:].mean()) / base,
                "same_month_last_year": float(
                    demand_map.get(target - 12, 0.0)
                )
                / base,
                "sku_season": float(
                    sku_season_map.get((sku_code, supplier, target.month), 1.0)
                ),
                "supplier_season": float(
                    supplier_season_map.get((supplier, target.month), 1.0)
                ),
                "growth_yoy": growth,
                "zero_share_12": float(np.mean(trailing == 0)),
                "stockout_months_12": int(
                    sum(bool(stockout_map.get(month, False)) for month in history_months)
                ),
                "target_month": int(target.month),
                "horizon": horizon,
                "supplier_feature": supplier_codes[supplier],
                "category_feature": category_codes[category],
            }
            rows.append(
                {
                    "sku_code": sku_code,
                    "supplier": supplier,
                    "origin": str(origin),
                    "month": str(target),
                    "base": base,
                    **values,
                }
            )
    return rows


def _build_training_frame_iterative(
    demand: pd.DataFrame,
    segments: pd.DataFrame,
    sku_ref: pd.DataFrame,
    train_end: pd.Period,
    horizons: Iterable[int] = range(1, 7),
) -> pd.DataFrame:
    """Build leakage-safe scaled examples whose targets do not exceed train_end."""

    train_end = pd.Period(train_end, freq="M")
    history = _regular_history(demand, segments)
    target_map = history.set_index([*KEYS, "period"])["demand"].to_dict()
    horizon_values = tuple(int(value) for value in horizons)
    rows: List[dict[str, object]] = []
    for origin in pd.period_range("2024-12", train_end - 1, freq="M"):
        valid_horizons = [
            horizon for horizon in horizon_values if origin + horizon <= train_end
        ]
        if not valid_horizons:
            continue
        origin_rows = _feature_rows(history, sku_ref, origin, valid_horizons)
        for row in origin_rows:
            target_period = pd.Period(str(row["month"]), freq="M")
            target = float(
                target_map.get(
                    (row["sku_code"], row["supplier"], target_period), 0.0
                )
            )
            row["target"] = target / float(row["base"])
        rows.extend(origin_rows)
    columns = [
        "sku_code",
        "supplier",
        "origin",
        "month",
        "base",
        *FEATURE_COLUMNS,
        "target",
    ]
    return pd.DataFrame(rows, columns=columns)


def _matrix_column(matrix: pd.DataFrame, period: pd.Period) -> np.ndarray:
    if period in matrix.columns:
        return matrix[period].to_numpy(dtype=float)
    return np.zeros(len(matrix), dtype=float)


def _seasonal_feature_matrices(
    demand_matrix: pd.DataFrame,
    supplier_codes: np.ndarray,
    supplier_count: int,
    origin: pd.Period,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized equivalent of the two approved seasonal-index functions."""

    sku_years = np.zeros((len(demand_matrix), 2, 12), dtype=float)
    for year_index, year in enumerate((2024, 2025)):
        for month in range(1, 13):
            period = pd.Period(year=year, month=month, freq="M")
            if period <= origin:
                sku_years[:, year_index, month - 1] = _matrix_column(
                    demand_matrix, period
                )

    supplier_years = np.zeros((supplier_count, 2, 12), dtype=float)
    for supplier_index in range(supplier_count):
        supplier_years[supplier_index] = sku_years[
            supplier_codes == supplier_index
        ].sum(axis=0)

    supplier_means = supplier_years.mean(axis=2)
    supplier_valid = supplier_means > 0
    supplier_normalized = np.divide(
        supplier_years,
        supplier_means[:, :, None],
        out=np.zeros_like(supplier_years),
        where=supplier_valid[:, :, None],
    )
    supplier_counts = supplier_valid.sum(axis=1)
    supplier_seasons = np.divide(
        supplier_normalized.sum(axis=1),
        supplier_counts[:, None],
        out=np.ones((supplier_count, 12), dtype=float),
        where=supplier_counts[:, None] > 0,
    )

    sku_means = sku_years.mean(axis=2)
    sku_valid = sku_years.sum(axis=2) > 0
    sku_normalized = np.divide(
        sku_years,
        sku_means[:, :, None],
        out=np.zeros_like(sku_years),
        where=sku_valid[:, :, None],
    )
    supplier_for_sku = supplier_seasons[supplier_codes]
    sku_seasons = np.where(
        sku_valid.all(axis=1)[:, None],
        sku_normalized.mean(axis=1),
        supplier_for_sku,
    )
    combined = np.clip(
        0.5 * sku_seasons + 0.5 * supplier_for_sku,
        0.3,
        3.0,
    )
    return combined, supplier_for_sku


def build_training_frame(
    demand: pd.DataFrame,
    segments: pd.DataFrame,
    sku_ref: pd.DataFrame,
    train_end: pd.Period,
    horizons: Iterable[int] = range(1, 7),
) -> pd.DataFrame:
    """Build the approved training examples with vectorized SKU operations."""

    train_end = pd.Period(train_end, freq="M")
    history = _regular_history(demand, segments)
    key_frame = history[KEYS].drop_duplicates().reset_index(drop=True)
    key_index = pd.MultiIndex.from_frame(key_frame)
    demand_matrix = (
        history.pivot(index=KEYS, columns="period", values="demand")
        .reindex(key_index)
        .fillna(0.0)
    )
    stockout_matrix = (
        history.pivot(index=KEYS, columns="period", values="is_stockout")
        .reindex(key_index)
        .fillna(False)
        .astype(bool)
    )

    supplier_names = sorted(history["supplier"].unique())
    supplier_map = {name: index for index, name in enumerate(supplier_names)}
    supplier_codes = key_frame["supplier"].map(supplier_map).to_numpy(dtype=int)
    category_map = _category_mapping(sku_ref)
    references = sku_ref.drop_duplicates(KEYS).set_index(KEYS)
    categories = references.reindex(key_index)["category"].astype(str)
    category_codes = categories.map(category_map).to_numpy(dtype=int)
    horizon_values = tuple(int(value) for value in horizons)
    row_frames = []

    for origin in pd.period_range("2024-12", train_end - 1, freq="M"):
        valid_horizons = np.array(
            [value for value in horizon_values if origin + value <= train_end],
            dtype=int,
        )
        if not len(valid_horizons):
            continue

        history_months = [origin - offset for offset in range(11, -1, -1)]
        trailing = np.column_stack(
            [_matrix_column(demand_matrix, month) for month in history_months]
        )
        base = trailing.mean(axis=1) + 1.0
        recent = trailing[:, -3:].sum(axis=1)
        prior = np.column_stack(
            [_matrix_column(demand_matrix, month - 12) for month in history_months[-3:]]
        ).sum(axis=1)
        growth = np.divide(
            recent,
            prior,
            out=np.ones_like(recent),
            where=prior != 0,
        )
        growth = np.clip(growth, 0.5, 2.0)
        stockouts = np.column_stack(
            [
                _matrix_column(stockout_matrix, month)
                for month in history_months
            ]
        ).sum(axis=1).astype(int)
        sku_seasons, supplier_seasons = _seasonal_feature_matrices(
            demand_matrix,
            supplier_codes,
            len(supplier_names),
            origin,
        )

        target_periods = [origin + int(value) for value in valid_horizons]
        target_months = np.array([period.month for period in target_periods])
        same_last_year = np.column_stack(
            [
                _matrix_column(demand_matrix, period - 12)
                for period in target_periods
            ]
        )
        targets = np.column_stack(
            [_matrix_column(demand_matrix, period) for period in target_periods]
        )
        horizon_count = len(valid_horizons)

        frame = pd.DataFrame(
            {
                "sku_code": np.repeat(key_frame["sku_code"].to_numpy(), horizon_count),
                "supplier": np.repeat(key_frame["supplier"].to_numpy(), horizon_count),
                "origin": str(origin),
                "month": np.tile([str(period) for period in target_periods], len(key_frame)),
                "base": np.repeat(base, horizon_count),
                "demand_lag_0": np.repeat(trailing[:, -1] / base, horizon_count),
                "demand_lag_1": np.repeat(trailing[:, -2] / base, horizon_count),
                "demand_lag_2": np.repeat(trailing[:, -3] / base, horizon_count),
                "demand_lag_5": np.repeat(trailing[:, -6] / base, horizon_count),
                "demand_lag_11": np.repeat(trailing[:, 0] / base, horizon_count),
                "rolling_mean_3": np.repeat(
                    trailing[:, -3:].mean(axis=1) / base, horizon_count
                ),
                "rolling_mean_6": np.repeat(
                    trailing[:, -6:].mean(axis=1) / base, horizon_count
                ),
                "same_month_last_year": (same_last_year / base[:, None]).ravel(),
                "sku_season": sku_seasons[:, target_months - 1].ravel(),
                "supplier_season": supplier_seasons[:, target_months - 1].ravel(),
                "growth_yoy": np.repeat(growth, horizon_count),
                "zero_share_12": np.repeat(
                    np.mean(trailing == 0, axis=1), horizon_count
                ),
                "stockout_months_12": np.repeat(stockouts, horizon_count),
                "target_month": np.tile(target_months, len(key_frame)),
                "horizon": np.tile(valid_horizons, len(key_frame)),
                "supplier_feature": np.repeat(supplier_codes, horizon_count),
                "category_feature": np.repeat(category_codes, horizon_count),
                "target": (targets / base[:, None]).ravel(),
            }
        )
        row_frames.append(frame)

    columns = [
        "sku_code",
        "supplier",
        "origin",
        "month",
        "base",
        *FEATURE_COLUMNS,
        "target",
    ]
    return pd.concat(row_frames, ignore_index=True)[columns]


def build_prediction_frame(
    demand: pd.DataFrame,
    segments: pd.DataFrame,
    sku_ref: pd.DataFrame,
    origin: pd.Period,
    horizons: Iterable[int],
) -> pd.DataFrame:
    """Build prediction features using demand no later than the origin."""

    history = _regular_history(demand, segments)
    rows = _feature_rows(history, sku_ref, pd.Period(origin, freq="M"), horizons)
    columns = [
        "sku_code",
        "supplier",
        "origin",
        "month",
        "base",
        *FEATURE_COLUMNS,
    ]
    return pd.DataFrame(rows, columns=columns)


def train_model(frame: pd.DataFrame) -> HistGradientBoostingRegressor:
    """Fit the pre-registered HistGradientBoostingRegressor configuration."""

    model = HistGradientBoostingRegressor(
        loss="absolute_error",
        learning_rate=0.05,
        max_iter=300,
        max_leaf_nodes=31,
        min_samples_leaf=50,
        l2_regularization=1.0,
        categorical_features=CATEGORICAL_FEATURES,
        random_state=0,
    )
    model.fit(frame[FEATURE_COLUMNS], frame["target"])
    model.training_rows_ = len(frame)
    return model


def predict(
    model: HistGradientBoostingRegressor, frame: pd.DataFrame
) -> pd.DataFrame:
    """Return finite non-negative forecasts restored to SKU units."""

    scaled = model.predict(frame[FEATURE_COLUMNS])
    result = frame[["sku_code", "supplier", "month"]].copy()
    result["ml_forecast"] = np.maximum(
        np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)
        * frame["base"].to_numpy(),
        0.0,
    )
    return result


def feature_importance(
    model: HistGradientBoostingRegressor, frame: pd.DataFrame
) -> pd.DataFrame:
    """Return the ten most influential features by permutation importance."""

    sample = frame.tail(min(len(frame), 5000))
    importance = permutation_importance(
        model,
        sample[FEATURE_COLUMNS],
        sample["target"],
        scoring="neg_mean_absolute_error",
        n_repeats=5,
        random_state=0,
    )
    return (
        pd.DataFrame(
            {"feature": FEATURE_COLUMNS, "importance": importance.importances_mean}
        )
        .sort_values("importance", ascending=False)
        .head(10)
        .reset_index(drop=True)
    )


__all__ = [
    "FEATURE_COLUMNS",
    "build_prediction_frame",
    "build_training_frame",
    "feature_importance",
    "predict",
    "train_model",
]
