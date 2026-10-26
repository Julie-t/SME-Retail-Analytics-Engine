"""FastAPI endpoints for metrics available from verified Gold tables."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Callable, TypeVar

from fastapi import FastAPI, HTTPException

from app.schemas import (
    AssistantAnswerResponse,
    AssistantAskRequest,
    BrandCountsResponse,
    CatalogMetricsResponse,
    CatalogCategorySummaryResponse,
    CatalogQualitySummaryResponse,
    CategoryCountsResponse,
    HealthResponse,
    ReviewBrandsResponse,
    ReviewCategoriesResponse,
    ReviewMetricsResponse,
    ReviewProductsResponse,
    ReviewQualitySummaryResponse,
    ReviewRatingDistributionResponse,
    ReviewRecommendationSummaryResponse,
    ReviewTrendsResponse,
)
from src.analytics.catalog_metrics import (
    CATALOG_TABLE,
    CatalogUnavailableError,
    load_catalog_brand_counts,
    load_catalog_category_summary,
    load_catalog_metrics,
    load_catalog_quality_summary,
)
from src.ai.assistant_service import GroqAnalyticsService
from src.analytics.review_metrics import (
    ReviewMetricsUnavailableError,
    load_review_brand_summary,
    load_review_category_summary,
    load_review_product_summary,
    load_review_quality_summary,
    load_review_rating_distribution,
    load_review_recommendation_summary,
    load_review_summary,
    load_review_trends,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "retail_engine.duckdb"
ReviewResponseT = TypeVar("ReviewResponseT")

app = FastAPI(
    title="Deterministic SME Retail Analytics API",
    version="1.0.0",
    description=(
        "Typed catalogue and review-grain metrics from verified DuckDB Gold marts. "
        "Listed product prices are catalogue attributes; transaction, revenue, margin, "
        "inventory, and customer metrics require separate verified source tables."
    ),
)


def get_database_path() -> Path:
    """Resolve the DuckDB file path, allowing deployments to override the default."""
    configured_path = os.environ.get("RETAIL_ENGINE_DB_PATH")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return DEFAULT_DATABASE_PATH


@lru_cache(maxsize=8)
def _cached_response(
    database_path: str,
    modified_time_ns: int,
    file_size: int,
) -> CatalogMetricsResponse:
    _ = modified_time_ns, file_size
    metrics = load_catalog_metrics(Path(database_path))
    return CatalogMetricsResponse.model_validate(
        {
            **metrics.__dict__,
            "category_counts": [
                item.__dict__ for item in metrics.category_counts
            ],
        }
    )


def _read_metrics() -> CatalogMetricsResponse:
    database_path = get_database_path()
    try:
        database_stat = database_path.stat()
    except OSError:
        database_stat = None

    try:
        if database_stat is None:
            metrics = load_catalog_metrics(database_path)
            return CatalogMetricsResponse.model_validate(
                {
                    **metrics.__dict__,
                    "category_counts": [
                        item.__dict__ for item in metrics.category_counts
                    ],
                }
            )
        else:
            return _cached_response(
                str(database_path),
                database_stat.st_mtime_ns,
                database_stat.st_size,
            )
    except CatalogUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@lru_cache(maxsize=8)
def _cached_category_summary(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> CatalogCategorySummaryResponse:
    _ = _modified_time_ns, _file_size
    categories = load_catalog_category_summary(Path(database_path))
    return CatalogCategorySummaryResponse.model_validate(
        {
            "categories": [
                item.__dict__ for item in categories
            ]
        }
    )


def _read_category_summary() -> CatalogCategorySummaryResponse:
    database_path = get_database_path()
    try:
        database_stat = database_path.stat()
        return _cached_category_summary(
            str(database_path),
            database_stat.st_mtime_ns,
            database_stat.st_size,
        )
    except OSError:
        try:
            categories = load_catalog_category_summary(database_path)
            return CatalogCategorySummaryResponse.model_validate(
                {"categories": [item.__dict__ for item in categories]}
            )
        except CatalogUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    except CatalogUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@lru_cache(maxsize=8)
def _cached_brand_counts(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> BrandCountsResponse:
    _ = _modified_time_ns, _file_size
    brands = load_catalog_brand_counts(Path(database_path))
    return BrandCountsResponse.model_validate(
        {"brands": [item.__dict__ for item in brands]}
    )


def _read_brand_counts() -> BrandCountsResponse:
    database_path = get_database_path()
    try:
        database_stat = database_path.stat()
        return _cached_brand_counts(
            str(database_path),
            database_stat.st_mtime_ns,
            database_stat.st_size,
        )
    except OSError:
        try:
            brands = load_catalog_brand_counts(database_path)
            return BrandCountsResponse.model_validate(
                {"brands": [item.__dict__ for item in brands]}
            )
        except CatalogUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    except CatalogUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@lru_cache(maxsize=8)
def _cached_quality_summary(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> CatalogQualitySummaryResponse:
    _ = _modified_time_ns, _file_size
    summary = load_catalog_quality_summary(Path(database_path))
    return CatalogQualitySummaryResponse.model_validate(summary.__dict__)


def _read_quality_summary() -> CatalogQualitySummaryResponse:
    database_path = get_database_path()
    try:
        database_stat = database_path.stat()
        return _cached_quality_summary(
            str(database_path),
            database_stat.st_mtime_ns,
            database_stat.st_size,
        )
    except OSError:
        try:
            summary = load_catalog_quality_summary(database_path)
            return CatalogQualitySummaryResponse.model_validate(summary.__dict__)
        except CatalogUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    except CatalogUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _read_review_response(
    cached_reader: Callable[[str, int, int], ReviewResponseT],
) -> ReviewResponseT:
    database_path = get_database_path()
    try:
        database_stat = database_path.stat()
        modified_time_ns = database_stat.st_mtime_ns
        file_size = database_stat.st_size
    except OSError:
        modified_time_ns = 0
        file_size = 0
    try:
        return cached_reader(str(database_path), modified_time_ns, file_size)
    except ReviewMetricsUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (TypeError, ValueError, OverflowError) as error:
        raise HTTPException(
            status_code=503,
            detail=f"Review Gold data is incompatible with its response contract: {error}",
        ) from error


@lru_cache(maxsize=8)
def _cached_review_summary(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> ReviewMetricsResponse:
    _ = _modified_time_ns, _file_size
    summary = load_review_summary(Path(database_path))
    return ReviewMetricsResponse.model_validate(summary.__dict__)


@lru_cache(maxsize=8)
def _cached_review_rating_distribution(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> ReviewRatingDistributionResponse:
    _ = _modified_time_ns, _file_size
    buckets = load_review_rating_distribution(Path(database_path))
    return ReviewRatingDistributionResponse.model_validate(
        {"ratings": [item.__dict__ for item in buckets]}
    )


@lru_cache(maxsize=8)
def _cached_review_recommendation_summary(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> ReviewRecommendationSummaryResponse:
    _ = _modified_time_ns, _file_size
    summary = load_review_recommendation_summary(Path(database_path))
    return ReviewRecommendationSummaryResponse.model_validate(summary.__dict__)


@lru_cache(maxsize=8)
def _cached_review_trends(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> ReviewTrendsResponse:
    _ = _modified_time_ns, _file_size
    trends = load_review_trends(Path(database_path))
    return ReviewTrendsResponse.model_validate(
        {"trends": [item.__dict__ for item in trends]}
    )


@lru_cache(maxsize=8)
def _cached_review_products(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> ReviewProductsResponse:
    _ = _modified_time_ns, _file_size
    products = load_review_product_summary(Path(database_path))
    return ReviewProductsResponse.model_validate(
        {"products": [item.__dict__ for item in products]}
    )


@lru_cache(maxsize=8)
def _cached_review_brands(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> ReviewBrandsResponse:
    _ = _modified_time_ns, _file_size
    brands = load_review_brand_summary(Path(database_path))
    return ReviewBrandsResponse.model_validate(
        {"brands": [item.__dict__ for item in brands]}
    )


@lru_cache(maxsize=8)
def _cached_review_categories(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> ReviewCategoriesResponse:
    _ = _modified_time_ns, _file_size
    categories = load_review_category_summary(Path(database_path))
    return ReviewCategoriesResponse.model_validate(
        {"categories": [item.__dict__ for item in categories]}
    )


@lru_cache(maxsize=8)
def _cached_review_quality(
    database_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> ReviewQualitySummaryResponse:
    _ = _modified_time_ns, _file_size
    summary = load_review_quality_summary(Path(database_path))
    return ReviewQualitySummaryResponse.model_validate(summary.__dict__)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    """Return ready only when the configured Gold catalog can be queried."""
    _read_metrics()
    return HealthResponse(status="ready", gold_table=CATALOG_TABLE)


@app.get(
    "/metrics/catalog",
    response_model=CatalogMetricsResponse,
    tags=["metrics"],
    summary="Product catalog quality and coverage metrics",
)
async def catalog_metrics() -> CatalogMetricsResponse:
    """Return deterministic product catalog counts and data-quality diagnostics."""
    return _read_metrics()


@app.get(
    "/metrics/catalog/categories",
    response_model=CategoryCountsResponse,
    tags=["metrics"],
    summary="Product counts by canonical category",
)
async def catalog_category_counts() -> CategoryCountsResponse:
    """Return product counts grouped by canonical category, including missing."""
    return CategoryCountsResponse(category_counts=_read_metrics().category_counts)


@app.get(
    "/metrics/catalog/category-summary",
    response_model=CatalogCategorySummaryResponse,
    tags=["metrics"],
    summary="Product counts and shares by category",
)
async def catalog_category_summary() -> CatalogCategorySummaryResponse:
    """Return category counts and shares from the Gold category summary."""
    return _read_category_summary()


@app.get(
    "/metrics/catalog/brands",
    response_model=BrandCountsResponse,
    tags=["metrics"],
    summary="Product counts by normalized brand",
)
async def catalog_brand_counts() -> BrandCountsResponse:
    """Return product counts and shares by normalized brand from Gold."""
    return _read_brand_counts()


@app.get(
    "/metrics/catalog/quality",
    response_model=CatalogQualitySummaryResponse,
    tags=["metrics"],
    summary="Catalog data-quality summary",
)
async def catalog_quality_summary() -> CatalogQualitySummaryResponse:
    """Return documented missing, invalid, duplicate, and quality-rate metrics."""
    return _read_quality_summary()


@app.get(
    "/metrics/reviews",
    response_model=ReviewMetricsResponse,
    tags=["review metrics"],
    summary="Review-grain totals, quality, ratings, and recommendations",
)
async def review_metrics() -> ReviewMetricsResponse:
    """Return review-row metrics, keeping them separate from product aggregates."""
    return _read_review_response(_cached_review_summary)


@app.get(
    "/metrics/reviews/ratings",
    response_model=ReviewRatingDistributionResponse,
    tags=["review metrics"],
    summary="Individual review rating distribution",
)
async def review_rating_distribution() -> ReviewRatingDistributionResponse:
    """Return rating shares over valid individual review ratings."""
    return _read_review_response(_cached_review_rating_distribution)


@app.get(
    "/metrics/reviews/recommendations",
    response_model=ReviewRecommendationSummaryResponse,
    tags=["review metrics"],
    summary="Individual review recommendation summary",
)
async def review_recommendation_summary() -> ReviewRecommendationSummaryResponse:
    """Return recommendation rates over rows with a valid recommendation value."""
    return _read_review_response(_cached_review_recommendation_summary)


@app.get(
    "/metrics/reviews/trends",
    response_model=ReviewTrendsResponse,
    tags=["review metrics"],
    summary="Review counts and metrics by submission month",
)
async def review_trends() -> ReviewTrendsResponse:
    """Return dated review counts with valid-rating and recommendation denominators."""
    return _read_review_response(_cached_review_trends)


@app.get(
    "/metrics/reviews/products",
    response_model=ReviewProductsResponse,
    tags=["review metrics"],
    summary="Review metrics for every reviewed product",
)
async def review_products() -> ReviewProductsResponse:
    """Return every product with loaded review rows, ranked deterministically."""
    return _read_review_response(_cached_review_products)


@app.get(
    "/metrics/reviews/brands",
    response_model=ReviewBrandsResponse,
    tags=["review metrics"],
    summary="Review metrics by product brand",
)
async def review_brands() -> ReviewBrandsResponse:
    """Return brand metrics including an explicit missing-brand bucket."""
    return _read_review_response(_cached_review_brands)


@app.get(
    "/metrics/reviews/categories",
    response_model=ReviewCategoriesResponse,
    tags=["review metrics"],
    summary="Review metrics by product category",
)
async def review_categories() -> ReviewCategoriesResponse:
    """Return category metrics including an explicit missing-category bucket."""
    return _read_review_response(_cached_review_categories)


@app.get(
    "/metrics/reviews/quality",
    response_model=ReviewQualitySummaryResponse,
    tags=["review metrics"],
    summary="Review source quality diagnostics",
)
async def review_quality_summary() -> ReviewQualitySummaryResponse:
    """Return source-backed missingness, invalidity, duplicate and mapping counts."""
    return _read_review_response(_cached_review_quality)


@app.post(
    "/assistant/ask",
    response_model=AssistantAnswerResponse,
    tags=["assistant"],
    summary="Natural-language analytics grounded in deterministic metrics",
)
async def assistant_ask(request: AssistantAskRequest) -> AssistantAnswerResponse:
    """Route a natural-language question to an allowlisted deterministic analytics operation."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    try:
        service = GroqAnalyticsService()
    except ValueError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Assistant configuration is invalid: {error}",
        ) from error
    if not service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not configured. Live Groq verification is pending.",
        )

    return service.ask(request.question, max_results=request.max_results)
