"""Validation and filesystem handling for complete supplier datasets."""

from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import BinaryIO, Callable, Iterable, Mapping, Optional

import pandas as pd

from app.loaders import iek, se
from app.loaders._shared import normalize_label, parse_month_label
from app.loaders import load_from_paths, supplier_paths


REQUIRED_TYPES = (
    "sales_tx",
    "sales_monthly",
    "stock_monthly",
    "in_transit",
    "moq",
)
TYPE_LABELS = {
    "sales_tx": "Транзакции продаж",
    "sales_monthly": "Продажи по месяцам",
    "stock_monthly": "Остатки по месяцам",
    "in_transit": "Товар в пути",
    "moq": "MOQ",
    "seasonality": "Сезонность",
}


@dataclass(frozen=True)
class FilePayload:
    name: str
    content: bytes


@dataclass(frozen=True)
class FileReport:
    name: str
    file_type: str | None
    ok: bool
    message: str


@dataclass(frozen=True)
class ValidatedDataset:
    supplier: str
    data_as_of: date
    sku_count: int
    sales_rows: int
    payloads: Mapping[str, FilePayload]
    row_counts: Mapping[str, int]
    reports: tuple[FileReport, ...]


@dataclass(frozen=True)
class DatasetContext:
    """Resolved current IEK and SE sources used as deterministic cache keys."""

    dataset_ids: Mapping[str, int | None]
    path_items: tuple[tuple[str, str, str], ...]
    current_rows: Mapping[str, Mapping[str, object]]

    @property
    def cache_key(self) -> tuple[object, object]:
        return tuple(self.dataset_ids[supplier] or "demo" for supplier in ("IEK", "SE"))

    @property
    def paths(self) -> dict[str, dict[str, Path]]:
        result = {"IEK": {}, "SE": {}}
        for supplier, file_type, path in self.path_items:
            result[supplier][file_type] = Path(path)
        return result


class DatasetValidationError(ValueError):
    """Validation failure carrying per-file results for the UI."""

    def __init__(self, message: str, reports: Iterable[FileReport] = ()) -> None:
        super().__init__(message)
        self.reports = tuple(reports)


def _payload(source: Path | BinaryIO | object) -> FilePayload:
    if isinstance(source, Path):
        return FilePayload(source.name, source.read_bytes())
    name = Path(str(getattr(source, "name", "файл.xlsx"))).name
    if hasattr(source, "getvalue"):
        content = bytes(source.getvalue())
    elif hasattr(source, "read"):
        position = source.tell() if hasattr(source, "tell") else None
        content = bytes(source.read())
        if position is not None and hasattr(source, "seek"):
            source.seek(position)
    else:
        raise TypeError(f"Неподдерживаемый источник файла: {type(source).__name__}")
    return FilePayload(name, content)


def _preview_rows(payload: FilePayload) -> list[set[str]]:
    try:
        preview = pd.read_excel(
            BytesIO(payload.content), header=None, nrows=12, dtype=object
        )
    except Exception as error:
        raise DatasetValidationError(
            f"{payload.name}: файл не читается как xlsx ({error})"
        ) from error
    return [
        {normalize_label(value) for value in row if not pd.isna(value)}
        for _, row in preview.iterrows()
    ]


def detect_file_type(source: Path | BinaryIO | object) -> str:
    """Identify a supported workbook by its header content, never its name."""

    payload = _payload(source)
    rows = _preview_rows(payload)
    for labels in rows:
        if {"дата", "документ", "код", "количество"}.issubset(labels):
            return "sales_tx"
        if "год" in labels and "итого" in labels:
            return "seasonality"
        if "артикул иэк" in labels and "код 1с" in labels:
            return "in_transit"
        if "категория 2026" in labels and "код 1с" in labels:
            return "in_transit"
        if "мин. разр. к отгр." in labels and "код 1с" in labels:
            return "moq"

        has_month = any(parse_month_label(label) is not None for label in labels)
        has_code = bool({"номенклатура.код", "код 1с", "код"} & labels)
        if has_month and "номенклатура" in labels and has_code:
            if {"ед.", "ед.изм", "ед"} & labels:
                return "stock_monthly"
            return "sales_monthly"
        if "кратность" in labels and "номенклатура" in labels and has_code:
            return "moq"
    raise DatasetValidationError(f"{payload.name}: тип файла не определён")


def _loader_error(label: str, filename: str, error: Exception) -> str:
    message = str(error)
    if "Could not find Excel header" in message:
        message = "не найдена строка с обязательными заголовками"
    elif "None of the columns" in message or "No column containing" in message:
        message = "не найдена обязательная колонка"
    return f"{label} ({filename}): {message}"


def validate_dataset(
    supplier: str, sources: Iterable[Path | BinaryIO | object]
) -> ValidatedDataset:
    """Validate one complete supplier upload without writing permanent files."""

    if supplier not in {"IEK", "SE"}:
        raise DatasetValidationError(f"Неизвестный поставщик: {supplier}")
    payloads: dict[str, FilePayload] = {}
    reports: list[FileReport] = []
    for source in sources:
        payload = _payload(source)
        if not payload.name.lower().endswith(".xlsx"):
            report = FileReport(payload.name, None, False, "нужен файл .xlsx")
            raise DatasetValidationError(report.message, [*reports, report])
        try:
            file_type = detect_file_type(BytesIOPayload(payload))
        except DatasetValidationError as error:
            report = FileReport(payload.name, None, False, str(error))
            raise DatasetValidationError(str(error), [*reports, report]) from error
        if file_type == "seasonality":
            reports.append(
                FileReport(
                    payload.name,
                    file_type,
                    True,
                    "Сезонность распознана и не используется",
                )
            )
            continue
        if file_type in payloads:
            report = FileReport(
                payload.name,
                file_type,
                False,
                f"дубликат типа «{TYPE_LABELS[file_type]}»",
            )
            raise DatasetValidationError(report.message, [*reports, report])
        payloads[file_type] = payload
        reports.append(
            FileReport(
                payload.name,
                file_type,
                True,
                f"определён тип «{TYPE_LABELS[file_type]}»",
            )
        )

    missing = [TYPE_LABELS[item] for item in REQUIRED_TYPES if item not in payloads]
    if missing:
        raise DatasetValidationError(
            "Не хватает файлов: " + ", ".join(missing), reports
        )

    loader = iek if supplier == "IEK" else se
    frames: dict[str, pd.DataFrame] = {}
    with TemporaryDirectory(prefix="astrea-dataset-") as directory:
        paths: dict[str, Path] = {}
        for file_type, payload in payloads.items():
            path = Path(directory) / f"{file_type}.xlsx"
            path.write_bytes(payload.content)
            paths[file_type] = path
        for file_type, function_name in (
            ("sales_tx", "load_sales_tx"),
            ("sales_monthly", "load_sales_monthly"),
            ("stock_monthly", "load_stock_monthly"),
            ("in_transit", "load_in_transit"),
            ("moq", "load_moq"),
        ):
            try:
                frames[file_type] = getattr(loader, function_name)(paths[file_type])
            except Exception as error:
                payload = payloads[file_type]
                message = _loader_error(TYPE_LABELS[file_type], payload.name, error)
                failed = FileReport(payload.name, file_type, False, message)
                raise DatasetValidationError(message, [*reports, failed]) from error

    sales = frames["sales_tx"]
    if sales.empty:
        raise DatasetValidationError("В транзакциях нет строк продаж", reports)
    sales_codes = set(sales["sku_code"].dropna().astype(str))
    stock_codes = set(frames["stock_monthly"]["sku_code"].dropna().astype(str))
    overlap = len(sales_codes & stock_codes) / len(sales_codes) if sales_codes else 0.0
    if overlap < 0.5:
        raise DatasetValidationError(
            f"Коды продаж и остатков пересекаются только на {overlap:.0%}", reports
        )
    data_as_of = pd.Timestamp(sales["date"].max())
    if pd.isna(data_as_of):
        raise DatasetValidationError("Не удалось определить дату среза", reports)
    return ValidatedDataset(
        supplier=supplier,
        data_as_of=data_as_of.date(),
        sku_count=len(sales_codes),
        sales_rows=len(sales),
        payloads=payloads,
        row_counts={file_type: len(frame) for file_type, frame in frames.items()},
        reports=tuple(reports),
    )


class BytesIOPayload(BytesIO):
    """Bytes stream retaining the source name for diagnostics."""

    def __init__(self, payload: FilePayload) -> None:
        super().__init__(payload.content)
        self.name = payload.name


def store_validated_files(dataset: ValidatedDataset, target: Path) -> dict[str, object]:
    """Write a validated upload to its permanent dataset directory."""

    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    metadata: dict[str, object] = {}
    try:
        for file_type, payload in dataset.payloads.items():
            (target / f"{file_type}.xlsx").write_bytes(payload.content)
            metadata[file_type] = {
                "name": payload.name,
                "size": len(payload.content),
                "rows": int(dataset.row_counts[file_type]),
            }
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return metadata


def resolve_dataset_context(
    connection_url: str, demo_dir: Path
) -> DatasetContext:
    """Resolve uploaded overrides while retaining demo data as the default."""

    from app.db import current_datasets

    paths = supplier_paths(Path(demo_dir))
    ids: dict[str, int | None] = {"IEK": None, "SE": None}
    current_rows: dict[str, Mapping[str, object]] = {}
    current = current_datasets(connection_url)
    for row in current.to_dict("records"):
        supplier = str(row["supplier"])
        storage_dir = Path(str(row["storage_dir"]))
        paths[supplier] = {
            file_type: storage_dir / f"{file_type}.xlsx"
            for file_type in REQUIRED_TYPES
        }
        ids[supplier] = int(row["id"])
        current_rows[supplier] = row
    path_items = tuple(
        (supplier, file_type, str(paths[supplier][file_type]))
        for supplier in ("IEK", "SE")
        for file_type in REQUIRED_TYPES
    )
    return DatasetContext(ids, path_items, current_rows)


def demo_dataset_context(demo_dir: Path) -> DatasetContext:
    """Return the deterministic context used before any supplier upload."""

    paths = supplier_paths(Path(demo_dir))
    path_items = tuple(
        (supplier, file_type, str(paths[supplier][file_type]))
        for supplier in ("IEK", "SE")
        for file_type in REQUIRED_TYPES
    )
    return DatasetContext({"IEK": None, "SE": None}, path_items, {})


def load_dataset_context(
    context: DatasetContext,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> dict[str, pd.DataFrame]:
    """Load canonical tables for a resolved pair of supplier datasets."""

    return load_from_paths(context.paths, on_progress=on_progress)


def save_validated_dataset(
    dataset: ValidatedDataset,
    uploaded_by: int,
    connection_url: str,
    upload_dir: Path,
) -> int:
    """Persist validated files and activate their database record."""

    from app.db import allocate_dataset_id, save_dataset

    dataset_id = allocate_dataset_id(connection_url)
    target = Path(upload_dir) / str(dataset_id)
    metadata = store_validated_files(dataset, target)
    try:
        save_dataset(
            dataset_id,
            dataset.supplier,
            uploaded_by,
            dataset.data_as_of,
            str(target),
            metadata,
            connection_url,
        )
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return dataset_id


__all__ = [
    "DatasetValidationError",
    "DatasetContext",
    "FilePayload",
    "FileReport",
    "REQUIRED_TYPES",
    "TYPE_LABELS",
    "ValidatedDataset",
    "detect_file_type",
    "demo_dataset_context",
    "load_dataset_context",
    "resolve_dataset_context",
    "save_validated_dataset",
    "store_validated_files",
    "validate_dataset",
]
