"""Command-line report for the historical forecast comparison."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine.backtest import _supplier_metrics, run_backtest  # noqa: E402,F401
from app.loaders import load_all  # noqa: E402


def main() -> None:
    results = run_backtest(load_all(ROOT / "data" / "raw"))
    print(
        f"ML training: rows={results.attrs['ml_training_rows']}, "
        f"seconds={results.attrs['ml_training_seconds']:.2f}"
    )
    for row in results.itertuples(index=False):
        print(f"{row.supplier}: SKU={row.sku_count}")
        print(
            f"  Formula: WAPE={row.our_wape:.4f} ({row.our_wape:.2%}), "
            f"MdAPE={row.our_mdape:.4f} ({row.our_mdape:.2%}), "
            f"bias={row.our_bias:+.2%}"
        )
        print(
            f"  ML: WAPE={row.ml_wape:.4f} ({row.ml_wape:.2%}), "
            f"MdAPE={row.ml_mdape:.4f} ({row.ml_mdape:.2%}), "
            f"bias={row.ml_bias:+.2%}"
        )
        print(
            f"  Partner: WAPE={row.partner_wape:.4f} ({row.partner_wape:.2%}), "
            f"MdAPE={row.partner_mdape:.4f} ({row.partner_mdape:.2%}), "
            f"bias={row.partner_bias:+.2%}"
        )
        print(
            "  Partner outliers (>10× 12-month average): "
            f"{row.partner_outlier_sku_count} SKU, "
            f"{row.partner_outlier_error_share:.2%} of partner absolute error"
        )
    print("ML feature importance (top 10):")
    for item in results.attrs["feature_importance"].itertuples(index=False):
        print(f"  {item.feature}: {item.importance:.6f}")


if __name__ == "__main__":
    main()
