"""Build the image-time canonical data cache for the demo dataset."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data_cache import write_cache  # noqa: E402
from app.datasets import demo_dataset_context, load_dataset_context  # noqa: E402


def main() -> None:
    context = demo_dataset_context(ROOT / "data" / "raw")
    tables = load_dataset_context(context)
    target = write_cache(ROOT / "data" / "cache", context.cache_key, tables)
    print(f"Built {target} for {context.cache_key}")


if __name__ == "__main__":
    main()
