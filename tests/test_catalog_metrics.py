from pathlib import Path

import duckdb
import polars as pl
import pytest
from fastapi.testclient import TestClient

from app.main import app
from src.analytics.catalog_metrics import (
    BRAND_SUMMARY_TABLE,
    CATEGORY_SUMMARY_TABLE,
    CATALOG_TABLE,
    QUALITY_SUMMARY_COLUMNS,
    QUALITY_SUMMARY_TABLE,
    BrandCount,
    CatalogCategoryMetric,
    CatalogQualitySummary,
    CategoryCount,
    CatalogUnavailableError,
    calculate_catalog_metrics,
    load_catalog_brand_counts,
    load_catalog_category_summary,
    load_catalog_metrics,
    load_catalog_quality_summary,
)

METRIC_COLUMNS = {
    "product_id": pl.String,
    "category": pl.String,
    "category_missing": pl.Boolean,
    "duplicate_product_id": pl.Boolean,
    "duplicate_brand_name_candidate": pl.Boolean,
    "ingredients_text_missing": pl.Boolean,
    "product_price_invalid": pl.Boolean,
    "product_rating_invalid": pl.Boolean,
    "aggregate_review_count_invalid": pl.Boolean,
    "loves_count_invalid": pl.Boolean,
}

QUALITY_VALUES = {
    "product_rows": 4,
    "distinct_product_ids": 4,
    "duplicate_product_id_rows": 0,
    "duplicate_product_id_groups": 0,
    "duplicate_brand_name_candidate_rows": 0,
    "missing_brand_rows": 0,
    "missing_product_name_rows": 0,
    "missing_category_rows": 1,
    "missing_ingredient_text_rows": 1,
    "missing_product_price_rows": 0,
    "invalid_product_price_rows": 1,
    "missing_product_rating_rows": 0,
    "invalid_product_rating_rows": 0,
    "missing_aggregate_review_count_rows": 0,
    "invalid_aggregate_review_count_rows": 0,
    "missing_loves_count_rows": 0,
    "invalid_loves_count_rows": 0,
    "rows_with_any_quality_issue": 2,
    "missing_brand_rate": 0.0,
    "missing_product_name_rate": 0.0,
    "missing_category_rate": 0.25,
    "missing_ingredient_text_rate": 0.25,
    "missing_product_price_rate": 0.0,
    "invalid_product_price_rate": 0.25,
    "missing_product_rating_rate": 0.0,
    "invalid_product_rating_rate": 0.0,
    "missing_aggregate_review_count_rate": 0.0,
    "invalid_aggregate_review_count_rate": 0.0,
    "missing_loves_count_rate": 0.0,
    "invalid_loves_count_rate": 0.0,
    "rows_with_any_quality_issue_rate": 0.5,
}


@pytest.fixture
def known_products() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "product_id": ["p1", "p2", "p3", None],
            "category": ["skincare", "skincare", "makeup", None],
            "category_missing": [False, False, False, True],
            "duplicate_product_id": [False, True, True, False],
            "duplicate_brand_name_candidate": [False, True, True, False],
            "ingredients_text_missing": [False, False, True, False],
            "product_price_invalid": [False, True, False, False],
            "product_rating_invalid": [False, False, True, False],
            "aggregate_review_count_invalid": [False, False, False, True],
            "loves_count_invalid": [False, False, False, False],
        },
        schema=METRIC_COLUMNS,
    )


def test_calculate_catalog_metrics_matches_known_values(
    known_products: pl.DataFrame,
) -> None:
    metrics = calculate_catalog_metrics(known_products)

    assert metrics.total_products == 4
    assert metrics.products_without_id == 1
    assert metrics.products_missing_category == 1
    assert metrics.duplicate_product_id_rows == 2
    assert metrics.duplicate_brand_name_candidate_rows == 2
    assert metrics.products_missing_ingredient_text == 1
    assert metrics.products_with_invalid_price == 1
    assert metrics.products_with_invalid_rating == 1
    assert metrics.products_with_invalid_aggregate_review_count == 1
    assert metrics.products_with_invalid_loves_count == 0
    assert metrics.category_counts == (
        CategoryCount("makeup", 1),
        CategoryCount("skincare", 2),
        CategoryCount(None, 1),
    )


def test_calculate_catalog_metrics_empty_frame() -> None:
    metrics = calculate_catalog_metrics(pl.DataFrame(schema=METRIC_COLUMNS))

    assert metrics.total_products == 0
    assert metrics.category_counts == ()


def test_calculate_catalog_metrics_rejects_missing_contract_column() -> None:
    with pytest.raises(ValueError, match="missing required metric columns"):
        calculate_catalog_metrics(pl.DataFrame({"product_id": ["p1"]}))


def test_calculate_catalog_metrics_rejects_null_quality_diagnostics(
    known_products: pl.DataFrame,
) -> None:
    products = known_products.with_columns(
        pl.Series(
            "product_price_invalid",
            [False, None, False, False],
            dtype=pl.Boolean,
        )
    )

    with pytest.raises(
        ValueError,
        match="null quality diagnostics: product_price_invalid",
    ):
        calculate_catalog_metrics(products)


def _create_gold_fixture(database_path: Path) -> None:
    with duckdb.connect(str(database_path)) as connection:
        metric_column_definitions = ", ".join(
            [
                "product_id VARCHAR",
                "category VARCHAR",
                "category_missing BOOLEAN",
                "duplicate_product_id BOOLEAN",
                "duplicate_brand_name_candidate BOOLEAN",
                "ingredients_text_missing BOOLEAN",
                "product_price_invalid BOOLEAN",
                "product_rating_invalid BOOLEAN",
                "aggregate_review_count_invalid BOOLEAN",
                "loves_count_invalid BOOLEAN",
            ]
        )
        connection.execute(
            f"CREATE TABLE {CATALOG_TABLE} ({metric_column_definitions})"
        )
        connection.executemany(
            f"INSERT INTO {CATALOG_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("p1", "skincare", False, False, False, False, False, False, False, False),
                ("p2", "skincare", False, False, False, False, False, False, False, False),
                ("p3", "makeup", False, False, False, True, True, False, False, False),
                ("p4", None, True, False, False, False, False, False, False, False),
            ],
        )
        connection.execute(
            f"""
            create table {CATEGORY_SUMMARY_TABLE} as
            select * from (values
                ('makeup'::varchar, 1::bigint, 0.25::double),
                ('skincare'::varchar, 2::bigint, 0.5::double),
                (null::varchar, 1::bigint, 0.25::double)
            ) as rows(category, product_rows, share_of_catalog_rows)
            """
        )
        connection.execute(
            f"""
            create table {BRAND_SUMMARY_TABLE} as
            select * from (values
                ('brand-a'::varchar, 'Brand A'::varchar, false, 3::bigint, 0.75::double),
                (null::varchar, null::varchar, true, 1::bigint, 0.25::double)
            ) as rows(brand_key, brand_name, brand_missing, product_rows, share_of_catalog_rows)
            """
        )
        selected = ", ".join(
            f"{QUALITY_VALUES[column]} AS {column}"
            for column in QUALITY_SUMMARY_COLUMNS
        )
        connection.execute(
            f"CREATE TABLE {QUALITY_SUMMARY_TABLE} AS SELECT {selected}"
        )


def _create_empty_gold_fixture(database_path: Path) -> None:
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            f"""
            create table {CATALOG_TABLE} (
                product_id varchar,
                category varchar,
                category_missing boolean,
                duplicate_product_id boolean,
                duplicate_brand_name_candidate boolean,
                ingredients_text_missing boolean,
                product_price_invalid boolean,
                product_rating_invalid boolean,
                aggregate_review_count_invalid boolean,
                loves_count_invalid boolean
            )
            """
        )


def test_load_catalog_metrics_reads_gold_table(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.duckdb"
    _create_gold_fixture(database_path)

    metrics = load_catalog_metrics(database_path)

    assert metrics.total_products == 4
    assert metrics.products_missing_category == 1
    assert metrics.products_missing_ingredient_text == 1
    assert metrics.products_with_invalid_price == 1


def test_load_catalog_category_summary_reads_gold_aggregate(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.duckdb"
    _create_gold_fixture(database_path)

    summary = load_catalog_category_summary(database_path)

    assert summary == (
        CatalogCategoryMetric("makeup", 1, 0.25),
        CatalogCategoryMetric("skincare", 2, 0.5),
        CatalogCategoryMetric(None, 1, 0.25),
    )


def test_load_catalog_brand_counts_reads_gold_aggregate(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.duckdb"
    _create_gold_fixture(database_path)

    brands = load_catalog_brand_counts(database_path)

    assert brands == (
        BrandCount("brand-a", "Brand A", False, 3, 0.75),
        BrandCount(None, None, True, 1, 0.25),
    )


def test_load_catalog_quality_summary_reads_gold_aggregate(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.duckdb"
    _create_gold_fixture(database_path)

    summary = load_catalog_quality_summary(database_path)

    assert isinstance(summary, CatalogQualitySummary)
    assert summary.product_rows == 4
    assert summary.distinct_product_ids == 4
    assert summary.missing_category_rows == 1
    assert summary.missing_ingredient_text_rows == 1
    assert summary.invalid_product_price_rows == 1
    assert summary.rows_with_any_quality_issue == 2
    assert summary.rows_with_any_quality_issue_rate == 0.5


def test_load_catalog_quality_summary_rejects_non_singleton_gold_table(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid_quality.duckdb"
    _create_gold_fixture(database_path)
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            f"""
            insert into {QUALITY_SUMMARY_TABLE}
            select * from {QUALITY_SUMMARY_TABLE}
            """
        )

    with pytest.raises(CatalogUnavailableError, match="exactly one row; found 2"):
        load_catalog_quality_summary(database_path)


def test_load_catalog_metrics_missing_database_is_explicit(
    tmp_path: Path,
) -> None:
    with pytest.raises(CatalogUnavailableError, match="does not exist"):
        load_catalog_metrics(tmp_path / "missing.duckdb")


def test_api_returns_typed_catalog_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "fixture.duckdb"
    _create_gold_fixture(database_path)
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))

    with TestClient(app) as client:
        response = client.get("/metrics/catalog")
        health = client.get("/health")
        categories = client.get("/metrics/catalog/categories")

    assert response.status_code == 200
    assert response.json() == {
        "total_products": 4,
        "products_without_id": 0,
        "products_missing_category": 1,
        "products_with_unmapped_category": None,
        "duplicate_product_id_rows": 0,
        "duplicate_brand_name_candidate_rows": 0,
        "products_missing_ingredient_text": 1,
        "invalid_ingredient_payload_rows": None,
        "products_with_invalid_price": 1,
        "products_with_invalid_rating": 0,
        "products_with_invalid_aggregate_review_count": 0,
        "products_with_invalid_loves_count": 0,
        "category_counts": [
            {"category": "makeup", "product_count": 1},
            {"category": "skincare", "product_count": 2},
            {"category": None, "product_count": 1},
        ],
    }
    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert categories.json() == {
        "category_counts": response.json()["category_counts"]
    }


def test_api_returns_gold_category_brand_and_quality_summaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "fixture.duckdb"
    _create_gold_fixture(database_path)
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))

    with TestClient(app) as client:
        categories = client.get("/metrics/catalog/category-summary")
        brands = client.get("/metrics/catalog/brands")
        quality = client.get("/metrics/catalog/quality")

    assert categories.status_code == 200
    assert categories.json()["categories"][0] == {
        "category": "makeup",
        "product_rows": 1,
        "share_of_catalog_rows": 0.25,
    }
    assert brands.status_code == 200
    assert brands.json()["brands"][0]["brand_key"] == "brand-a"
    assert quality.status_code == 200
    assert quality.json()["product_rows"] == 4
    assert quality.json()["missing_category_rows"] == 1
    assert quality.json()["missing_ingredient_text_rows"] == 1
    assert quality.json()["invalid_product_price_rows"] == 1
    assert quality.json()["missing_ingredient_payload_rows"] == 1
    assert quality.json()["invalid_ingredient_json_rows"] is None
    assert quality.json()["missing_origin_rows"] is None
    assert quality.json()["rows_with_any_quality_issue_rate"] == 0.5


def test_api_reports_missing_database_as_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(tmp_path / "missing.duckdb"))

    with TestClient(app) as client:
        response = client.get("/metrics/catalog")
        health = client.get("/health")

    assert response.status_code == 503
    assert "does not exist" in response.json()["detail"]
    assert health.status_code == 503


def test_api_reports_missing_gold_table_as_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "without_gold.duckdb"
    with duckdb.connect(str(database_path)):
        pass
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))

    with TestClient(app) as client:
        response = client.get("/metrics/catalog")
        brand_counts = client.get("/metrics/catalog/brands")
        quality = client.get("/metrics/catalog/quality")
        health = client.get("/health")

    assert response.status_code == 503
    assert CATALOG_TABLE in response.json()["detail"]
    assert brand_counts.status_code == 503
    assert BRAND_SUMMARY_TABLE in brand_counts.json()["detail"]
    assert quality.status_code == 503
    assert QUALITY_SUMMARY_TABLE in quality.json()["detail"]
    assert health.status_code == 503


def test_api_returns_empty_metrics_for_an_empty_gold_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "empty_gold.duckdb"
    _create_empty_gold_fixture(database_path)
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))

    with TestClient(app) as client:
        response = client.get("/metrics/catalog")

    assert response.status_code == 200
    assert response.json() == {
        "total_products": 0,
        "products_without_id": 0,
        "products_missing_category": 0,
        "products_with_unmapped_category": None,
        "duplicate_product_id_rows": 0,
        "duplicate_brand_name_candidate_rows": 0,
        "products_missing_ingredient_text": 0,
        "invalid_ingredient_payload_rows": None,
        "products_with_invalid_price": 0,
        "products_with_invalid_rating": 0,
        "products_with_invalid_aggregate_review_count": 0,
        "products_with_invalid_loves_count": 0,
        "category_counts": [],
    }


def test_api_publishes_openapi_documentation() -> None:
    with TestClient(app) as client:
        docs = client.get("/docs")
        openapi = client.get("/openapi.json")

    assert docs.status_code == 200
    assert openapi.status_code == 200
    assert "/metrics/catalog" in openapi.json()["paths"]
