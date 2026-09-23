from pathlib import Path

import pandas as pd
import pytest
from pandas.api.types import is_datetime64_any_dtype, is_float_dtype, is_integer_dtype

from app.loaders import load_all
from app.loaders import iek, se
from app.models import TABLE_COLUMNS


FIXTURES = Path(__file__).parent / "fixtures"
MONTH_NAMES = {
    1: "янв.",
    2: "февр.",
    3: "март",
    4: "апр.",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "авг.",
    9: "сент.",
    10: "окт.",
    11: "нояб.",
    12: "дек.",
}


def _month_header(value: str) -> str:
    year, month = (int(part) for part in value.split("-"))
    return f"{MONTH_NAMES[month]} {year}"


def _monthly_source(source_name: str, supplier: str, stock: bool) -> pd.DataFrame:
    source = pd.read_csv(FIXTURES / source_name)
    month_columns = [column for column in source.columns if column[:2] == "20"]
    renamed_months = {column: _month_header(column) for column in month_columns}

    if supplier == "IEK":
        metadata = pd.DataFrame(
            {
                "Номенклатура": source["name"],
                **({"Ед.": "шт"} if stock else {}),
                "Номенклатура.Код": source["sku_code"],
            }
        )
    else:
        metadata = pd.DataFrame(
            {
                **({"№": range(1, len(source) + 1)} if stock else {}),
                "Номенклатура": source["name"],
                "Номенклатура.Код": source["sku_code"],
                **(
                    {"Ед.изм": "шт"}
                    if stock
                    else {"Артикул": [f"A-{index}" for index in range(1, len(source) + 1)], "Кратность": 1}
                ),
            }
        )

    values = source[month_columns].rename(columns=renamed_months)
    result = pd.concat([metadata, values], axis=1)
    service_rows = 2 if stock else 1
    service = pd.DataFrame([{column: None for column in result.columns}] * service_rows)
    for month_column in renamed_months.values():
        service.loc[:, month_column] = "нач. остаток" if stock else "Количество"
    return pd.concat([service, result], ignore_index=True)


def _write_supplier_files(root: Path, supplier: str) -> None:
    directory = root / ("IEK" if supplier == "IEK" else "Systeme electric")
    directory.mkdir(parents=True)
    tx = pd.read_csv(FIXTURES / "sales_tx.csv")
    sales = _monthly_source("monthly_sales.csv", supplier, stock=False)
    stock = _monthly_source("monthly_stock.csv", supplier, stock=True)

    if supplier == "IEK":
        tx.to_excel(directory / "Динамика продаж_fixture.xlsx", index=False)
        sales.to_excel(directory / "Ежемесячные продажи_fixture.xlsx", index=False)
        stock.to_excel(directory / "Ежемесячные остатки_fixture.xlsx", index=False)
        pd.DataFrame(
            {
                "Код 1с": ["SEASONAL-1", "STOCKOUT-1", "OUTLIER-1"],
                "Артикул ИЭК": ["A-1", "A-2", "A-3"],
                " Наименование": ["Seasonal fixture", "Stockout fixture", "Outlier fixture"],
                "Поставка 1": [4, None, 2],
                "Поставка 2": [3, 5, None],
            }
        ).to_excel(directory / "Путь_fixture.xlsx", index=False)
        pd.DataFrame(
            {
                "Код 1с": ["SEASONAL-1", "STOCKOUT-1"],
                "Артикул поставщика": ["A-1", "A-2"],
                "Наименование": ["Seasonal fixture", "Stockout fixture"],
                "Мин. разр. к отгр.": [6, None],
            }
        ).to_excel(directory / "MOQ_fixture.xlsx", index=False)
    else:
        tx.to_excel(directory / "Динамика продаж_fixture.xlsx", index=False)
        sales.to_excel(directory / "Ежемесячные продажи_fixture.xlsx", index=False)
        stock.to_excel(directory / "Ежемесячные остатки_fixture.xlsx", index=False)
        transit = pd.DataFrame(
            {
                "№": [1, 2, 3],
                "Артикул поставщика": ["A-1", "A-2", "A-3"],
                "Код 1с": ["SEASONAL-1", "STOCKOUT-1", "OUTLIER-1"],
                "Наименование": ["Seasonal fixture", "Stockout fixture", "Outlier fixture"],
                "Кэф. Роста": [1.2, 1.0, 1.0],
                "Свободный остаток": [11, 12, None],
                "СЭ в пути 24.09": [7, 5, 2],
            }
        )
        with pd.ExcelWriter(directory / "Товар в пути_fixture.xlsx") as writer:
            transit.to_excel(writer, index=False, startrow=1)
        pd.DataFrame(
            {
                "№": [1, 2],
                "Номенклатура": ["Seasonal fixture", "Stockout fixture"],
                "Номенклатура.Код": ["SEASONAL-1", "STOCKOUT-1"],
                "Артикул": ["A-1", "A-2"],
                "Кратность": [6, None],
            }
        ).to_excel(directory / "MOQ fixture.xlsx", index=False)


@pytest.fixture()
def synthetic_data_dir(tmp_path: Path) -> Path:
    _write_supplier_files(tmp_path, "IEK")
    _write_supplier_files(tmp_path, "SE")
    return tmp_path


@pytest.mark.parametrize(("supplier", "loader"), [("IEK", iek), ("SE", se)])
def test_sales_transactions_are_filtered_and_normalized(
    synthetic_data_dir: Path, supplier: str, loader: object
) -> None:
    directory = synthetic_data_dir / ("IEK" if supplier == "IEK" else "Systeme electric")
    frame = loader.load_sales_tx(directory / "Динамика продаж_fixture.xlsx")

    assert tuple(frame.columns) == TABLE_COLUMNS["sales_tx"]
    assert len(frame) == 13
    assert set(frame["supplier"]) == {supplier}
    assert frame["qty"].min() >= 0
    assert is_datetime64_any_dtype(frame["date"])
    assert is_float_dtype(frame["qty"])


@pytest.mark.parametrize(("supplier", "loader"), [("IEK", iek), ("SE", se)])
def test_monthly_loaders_return_canonical_columns_and_values(
    synthetic_data_dir: Path, supplier: str, loader: object
) -> None:
    directory = synthetic_data_dir / ("IEK" if supplier == "IEK" else "Systeme electric")
    sales = loader.load_sales_monthly(directory / "Ежемесячные продажи_fixture.xlsx")
    stock = loader.load_stock_monthly(directory / "Ежемесячные остатки_fixture.xlsx")

    assert tuple(sales.columns) == TABLE_COLUMNS["sales_monthly"]
    assert tuple(stock.columns) == TABLE_COLUMNS["stock_monthly"]
    assert len(sales) == len(stock) == 36
    assert set(sales["month"]) == {f"2025-{month:02d}" for month in range(1, 13)}
    assert is_float_dtype(sales["qty"])
    assert is_float_dtype(stock["opening_stock"])
    assert not stock["opening_stock"].isna().any()
    stockout = stock.loc[stock["sku_code"].eq("STOCKOUT-1")]
    assert stockout.loc[stockout["month"].isin(["2025-03", "2025-04"]), "opening_stock"].eq(0).all()


def test_supplier_specific_transit_and_moq_are_normalized(synthetic_data_dir: Path) -> None:
    iek_dir = synthetic_data_dir / "IEK"
    se_dir = synthetic_data_dir / "Systeme electric"

    iek_transit = iek.load_in_transit(iek_dir / "Путь_fixture.xlsx")
    se_transit = se.load_in_transit(se_dir / "Товар в пути_fixture.xlsx")
    iek_moq = iek.load_moq(iek_dir / "MOQ_fixture.xlsx")
    se_moq = se.load_moq(se_dir / "MOQ fixture.xlsx")

    assert iek_transit.set_index("sku_code").loc["SEASONAL-1", "qty"] == 7
    assert se_transit.set_index("sku_code").loc["SEASONAL-1", "qty"] == 7
    assert iek_moq.set_index("sku_code").loc["STOCKOUT-1", "moq"] == 1
    assert se_moq.set_index("sku_code").loc["STOCKOUT-1", "moq"] == 1
    assert is_integer_dtype(iek_moq["moq"])


def test_load_all_combines_suppliers_and_fills_missing_moq(synthetic_data_dir: Path) -> None:
    tables = load_all(synthetic_data_dir)

    assert set(tables) == set(TABLE_COLUMNS)
    for table_name, frame in tables.items():
        assert not frame.empty
        assert tuple(frame.columns) == TABLE_COLUMNS[table_name]
        assert set(frame["supplier"]) == {"IEK", "SE"}

    default_moq = tables["moq"].loc[tables["moq"]["sku_code"].eq("OUTLIER-1"), "moq"]
    assert default_moq.eq(1).all()
    assert len(tables["sku_ref"]) == 6
    assert tuple(tables["current_stock"].columns) == TABLE_COLUMNS["current_stock"]
    se_stock = tables["current_stock"].loc[tables["current_stock"]["supplier"].eq("SE")]
    assert se_stock.set_index("sku_code").loc["SEASONAL-1", "free_stock"] == 11
    assert se_stock.set_index("sku_code").loc["OUTLIER-1", "free_stock"] == 0
    assert ("OUTLIER-1", "SE") in tables["current_stock"].attrs["estimated_keys"]
    assert set(tables["sku_ref"]["unit"]) == {"шт"}
    assert tables["sku_ref"]["article"].str.startswith("A-").all()
