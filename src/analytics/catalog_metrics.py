"""Typed, deterministic metrics over the Gold product catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

CATALOG_TABLE = "main.mart_product_catalog"
METRIC_COLUMNS = (
    "product_id",
    "category",
    "category_missing",
    "duplicate_product_id",
    "duplicate_brand_name_candidate",
    "ingredients_text_missing",
    "product_price_invalid",
    "product_rating_invalid",
    "aggregate_review_count_invalid",
    "loves_count_invalid",
)
CATEGORY_SUMMARY_TABLE = "main.mart_catalog_by_category"
BRAND_SUMMARY_TABLE = "main.mart_catalog_by_brand"
QUALITY_SUMMARY_TABLE = "main.mart_catalog_quality_summary"
QUALITY_SUMMARY_COLUMNS = (
    "product_rows",
    "distinct_product_ids",
    "duplicate_product_id_rows",
    "duplicate_product_id_groups",
    "duplicate_brand_name_candidate_rows",
    "missing_brand_rows",
    "missing_product_name_rows",
    "missing_category_rows",
    "missing_ingredient_text_rows",
    "missing_product_price_rows",
    "invalid_product_price_rows",
    "missing_product_rating_rows",
    "invalid_product_rating_rows",
    "missing_aggregate_review_count_rows",
    "invalid_aggregate_review_count_rows",
    "missing_loves_count_rows",
    "invalid_loves_count_rows",
    "rows_with_any_quality_issue",
    "missing_brand_rate",
    "missing_product_name_rate",
    "missing_category_rate",
    "missing_ingredient_text_rate",
    "missing_product_price_rate",
    "invalid_product_price_rate",
    "missing_product_rating_rate",
    "invalid_product_rating_rate",
    "missing_aggregate_review_count_rate",
    "invalid_aggregate_review_count_rate",
    "missing_loves_count_rate",
    "invalid_loves_count_rate",
    "rows_with_any_quality_issue_rate",
)


class CatalogUnavailableError(RuntimeError):
    """Raised when the configured Gold product catalog cannot be read."""


@dataclass(frozen=True)
class CategoryCount:
    category: str | None
    product_count: int


@dataclass(frozen=True)
class CatalogCategoryMetric:
    category: str | None
    product_rows: int
    share_of_catalog_rows: float | None


@dataclass(frozen=True)
class BrandCount:
    brand_key: str | None
    brand_name: str | None
    brand_missing: bool
    product_rows: int
    share_of_catalog_rows: float | None


@dataclass(frozen=True)
class CatalogQualitySummary:
    product_rows: int
    distinct_product_ids: int
    duplicate_product_id_rows: int
    duplicate_product_id_groups: int
    duplicate_brand_name_candidate_rows: int
    missing_brand_rows: int
    missing_product_name_rows: int
    missing_category_rows: int
    missing_ingredient_text_rows: int
    missing_product_price_rows: int
    invalid_product_price_rows: int
    missing_product_rating_rows: int
    invalid_product_rating_rows: int
    missing_aggregate_review_count_rows: int
    invalid_aggregate_review_count_rows: int
    missing_loves_count_rows: int
    invalid_loves_count_rows: int
    rows_with_any_quality_issue: int
    missing_brand_rate: float | None
    missing_product_name_rate: float | None
    missing_category_rate: float | None
    missing_ingredient_text_rate: float | None
    missing_product_price_rate: float | None
    invalid_product_price_rate: float | None
    missing_product_rating_rate: float | None
    invalid_product_rating_rate: float | None
    missing_aggregate_review_count_rate: float | None
    invalid_aggregate_review_count_rate: float | None
    missing_loves_count_rate: float | None
    invalid_loves_count_rate: float | None
    rows_with_any_quality_issue_rate: float | None
    unmapped_category_rows: int | None = None
    missing_origin_rows: int | None = None
    missing_formulation_attributes_rows: int | None = None
    missing_ingredient_payload_rows: int | None = None
    invalid_ingredient_json_rows: int | None = None
    non_array_ingredient_payload_rows: int | None = None
    invalid_ingredient_entry_rows: int | None = None
    unmapped_category_rate: float | None = None
    missing_origin_rate: float | None = None
    missing_formulation_attributes_rate: float | None = None
    missing_ingredient_payload_rate: float | None = None
    invalid_ingredient_json_rate: float | None = None
    non_array_ingredient_payload_rate: float | None = None
    invalid_ingredient_entry_rate: float | None = None


@dataclass(frozen=True)
class CatalogMetrics:
    total_products: int
    products_without_id: int
    products_missing_category: int
    products_with_unmapped_category: int | None
    duplicate_product_id_rows: int
    duplicate_brand_name_candidate_rows: int
    products_missing_ingredient_text: int
    invalid_ingredient_payload_rows: int | None
    products_with_invalid_price: int
    products_with_invalid_rating: int
    products_with_invalid_aggregate_review_count: int
    products_with_invalid_loves_count: int
    category_counts: tuple[CategoryCount, ...]


def calculate_catalog_metrics(products: pl.DataFrame) -> CatalogMetrics:
    """Calculate catalog counts from a frame matching the Gold mart contract."""
    missing_columns = sorted(set(METRIC_COLUMNS).difference(products.columns))
    if missing_columns:
        raise ValueError(
            "Product catalog is missing required metric columns: "
            + ", ".join(missing_columns)
        )

    diagnostic_columns = set(METRIC_COLUMNS) - {"product_id", "category"}
    nullable_diagnostics = sorted(
        column
        for column in diagnostic_columns
        if products[column].null_count() > 0
    )
    if nullable_diagnostics:
        raise ValueError(
            "Product catalog contains null quality diagnostics: "
            + ", ".join(nullable_diagnostics)
        )

    metrics_frame = products.select(
        pl.col("product_id"),
        pl.col("category"),
        pl.col("category_missing"),
        pl.col("duplicate_product_id"),
        pl.col("duplicate_brand_name_candidate"),
        pl.col("ingredients_text_missing"),
        pl.col("product_price_invalid"),
        pl.col("product_rating_invalid"),
        pl.col("aggregate_review_count_invalid"),
        pl.col("loves_count_invalid"),
    )

    total_products = metrics_frame.height

    def count_true(column: str) -> int:
        count = metrics_frame[column].sum()
        return 0 if count is None else int(count)

    if total_products == 0:
        category_counts: tuple[CategoryCount, ...] = ()
    else:
        grouped = (
            metrics_frame.group_by("category")
            .agg(pl.len().alias("product_count"))
            .sort("category", nulls_last=True)
        )
        category_counts = tuple(
            CategoryCount(
                category=row["category"],
                product_count=int(row["product_count"]),
            )
            for row in grouped.iter_rows(named=True)
        )

    return CatalogMetrics(
        total_products=total_products,
        products_without_id=int(metrics_frame["product_id"].null_count()),
        products_missing_category=count_true("category_missing"),
        products_with_unmapped_category=None,
        duplicate_product_id_rows=count_true("duplicate_product_id"),
        duplicate_brand_name_candidate_rows=count_true(
            "duplicate_brand_name_candidate"
        ),
        products_missing_ingredient_text=count_true("ingredients_text_missing"),
        invalid_ingredient_payload_rows=None,
        products_with_invalid_price=count_true("product_price_invalid"),
        products_with_invalid_rating=count_true("product_rating_invalid"),
        products_with_invalid_aggregate_review_count=count_true(
            "aggregate_review_count_invalid"
        ),
        products_with_invalid_loves_count=count_true("loves_count_invalid"),
        category_counts=category_counts,
    )


def load_catalog_category_summary(database_path: Path) -> tuple[CatalogCategoryMetric, ...]:
    """Read category counts and row shares from the Gold aggregate mart."""
    if not database_path.is_file():
        raise CatalogUnavailableError(
            f"Configured DuckDB file does not exist: {database_path}"
        )
    query = f"""
        select category, product_rows, share_of_catalog_rows
        from {CATEGORY_SUMMARY_TABLE}
        order by category nulls last
    """
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            rows = connection.execute(query).fetchall()
    except duckdb.Error as error:
        raise CatalogUnavailableError(
            f"Required Gold table {CATEGORY_SUMMARY_TABLE} is unavailable or incompatible: {error}"
        ) from error
    return tuple(
        CatalogCategoryMetric(
            category=category,
            product_rows=int(product_rows),
            share_of_catalog_rows=(
                float(share) if share is not None else None
            ),
        )
        for category, product_rows, share in rows
    )


def load_catalog_brand_counts(database_path: Path) -> tuple[BrandCount, ...]:
    """Read normalized-brand counts and row shares from the Gold aggregate mart."""
    if not database_path.is_file():
        raise CatalogUnavailableError(
            f"Configured DuckDB file does not exist: {database_path}"
        )
    query = f"""
        select brand_key, brand_name, brand_missing, product_rows, share_of_catalog_rows
        from {BRAND_SUMMARY_TABLE}
        order by brand_key nulls last
    """
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            rows = connection.execute(query).fetchall()
    except duckdb.Error as error:
        raise CatalogUnavailableError(
            f"Required Gold table {BRAND_SUMMARY_TABLE} is unavailable or incompatible: {error}"
        ) from error
    return tuple(
        BrandCount(
            brand_key=brand_key,
            brand_name=brand_name,
            brand_missing=bool(brand_missing),
            product_rows=int(product_rows),
            share_of_catalog_rows=(
                float(share) if share is not None else None
            ),
        )
        for brand_key, brand_name, brand_missing, product_rows, share in rows
    )


def load_catalog_quality_summary(database_path: Path) -> CatalogQualitySummary:
    """Read the single aggregate quality row from the Gold summary mart."""
    if not database_path.is_file():
        raise CatalogUnavailableError(
            f"Configured DuckDB file does not exist: {database_path}"
        )
    selected_columns = ", ".join(f'"{column}"' for column in QUALITY_SUMMARY_COLUMNS)
    query = f"select {selected_columns} from {QUALITY_SUMMARY_TABLE}"
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            rows = connection.execute(query).fetchall()
    except duckdb.Error as error:
        raise CatalogUnavailableError(
            f"Required Gold table {QUALITY_SUMMARY_TABLE} is unavailable or incompatible: {error}"
        ) from error
    if len(rows) != 1:
        raise CatalogUnavailableError(
            f"Required Gold table {QUALITY_SUMMARY_TABLE} must contain exactly one row; "
            f"found {len(rows)}."
        )
    values = dict(zip(QUALITY_SUMMARY_COLUMNS, rows[0], strict=True))
    counts = {
        column: int(values[column])
        for column in QUALITY_SUMMARY_COLUMNS
        if column.endswith("_rows")
        or column.endswith("_ids")
        or column.endswith("_groups")
        or column == "rows_with_any_quality_issue"
    }
    rates = {
        column: float(values[column]) if values[column] is not None else None
        for column in QUALITY_SUMMARY_COLUMNS
        if column.endswith("_rate")
    }
    return CatalogQualitySummary(
        **counts,
        **rates,
        missing_ingredient_payload_rows=counts["missing_ingredient_text_rows"],
        missing_ingredient_payload_rate=rates["missing_ingredient_text_rate"],
    )


def load_catalog_metrics(database_path: Path) -> CatalogMetrics:
    """Read the required Gold table and calculate catalog metrics."""
    if not database_path.is_file():
        raise CatalogUnavailableError(
            f"Configured DuckDB file does not exist: {database_path}"
        )

    selected_columns = ", ".join(f'"{column}"' for column in METRIC_COLUMNS)
    query = f"select {selected_columns} from {CATALOG_TABLE}"
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            result = connection.execute(query)
            column_names = [item[0] for item in result.description]
            rows = result.fetchall()
    except duckdb.Error as error:
        raise CatalogUnavailableError(
            f"Required Gold table {CATALOG_TABLE} is unavailable or incompatible: {error}"
        ) from error

    frame = pl.DataFrame(rows, schema=column_names, orient="row")
    try:
        return calculate_catalog_metrics(frame)
    except ValueError as error:
        raise CatalogUnavailableError(str(error)) from error
