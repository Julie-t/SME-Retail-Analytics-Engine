"""Typed, read-only review analytics over the Gold review marts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

REVIEW_SUMMARY_TABLE = "main.mart_review_summary"
REVIEW_RATING_TABLE = "main.mart_review_rating_distribution"
REVIEW_RECOMMENDATION_TABLE = "main.mart_review_recommendation_summary"
REVIEW_TRENDS_TABLE = "main.mart_review_monthly_trends"
REVIEW_PRODUCT_TABLE = "main.mart_review_product_summary"
REVIEW_BRAND_TABLE = "main.mart_review_brand_summary"
REVIEW_CATEGORY_TABLE = "main.mart_review_category_summary"
REVIEW_QUALITY_TABLE = "main.mart_review_quality_summary"


class ReviewMetricsUnavailableError(RuntimeError):
    """Raised when a required Gold review relation cannot be read."""


@dataclass(frozen=True)
class ReviewSummary:
    total_review_rows: int
    distinct_product_ids: int
    valid_rating_rows: int
    invalid_rating_rows: int
    average_rating: float | None
    median_rating: float | None
    missing_product_id_rows: int
    missing_rating_rows: int
    missing_recommendation_rows: int
    invalid_recommendation_rows: int
    missing_submission_time_rows: int
    missing_review_text_rows: int
    missing_review_title_rows: int
    duplicate_review_candidate_rows: int
    orphan_product_id_rows: int
    recommended_review_rows: int
    not_recommended_review_rows: int
    valid_recommendation_rows: int
    recommendation_rate: float | None
    helpfulness_review_rows: int
    total_feedback_votes: int
    positive_feedback_votes: int
    negative_feedback_votes: int
    helpfulness_missing_rows: int
    helpfulness_invalid_rows: int
    invalid_feedback_count_rows: int
    average_helpfulness: float | None
    weighted_helpfulness_rate: float | None
    rows_with_quality_issue: int
    rows_with_quality_issue_rate: float | None


@dataclass(frozen=True)
class ReviewRatingBucket:
    rating: float
    review_rows: int
    valid_rating_rows: int
    share_of_valid_ratings: float | None


@dataclass(frozen=True)
class ReviewRecommendationSummary:
    recommended_review_rows: int
    not_recommended_review_rows: int
    missing_recommendation_rows: int
    invalid_recommendation_rows: int
    valid_recommendation_rows: int
    recommendation_rate: float | None


@dataclass(frozen=True)
class ReviewTrend:
    month: str
    review_rows: int
    valid_rating_rows: int
    average_rating: float | None
    valid_recommendation_rows: int
    recommendation_rate: float | None


@dataclass(frozen=True)
class ReviewProductSummary:
    product_id: str | None
    product_name: str | None
    review_rows: int
    valid_rating_rows: int
    average_rating: float | None
    valid_recommendation_rows: int
    recommendation_rate: float | None


@dataclass(frozen=True)
class ReviewBrandSummary:
    brand_key: str | None
    brand_name: str | None
    review_rows: int
    valid_rating_rows: int
    average_rating: float | None
    valid_recommendation_rows: int
    recommendation_rate: float | None


@dataclass(frozen=True)
class ReviewCategorySummary:
    category: str | None
    review_rows: int
    valid_rating_rows: int
    average_rating: float | None
    valid_recommendation_rows: int
    recommendation_rate: float | None


@dataclass(frozen=True)
class ReviewQualitySummary:
    total_review_rows: int
    missing_product_id_rows: int
    missing_rating_rows: int
    invalid_rating_rows: int
    missing_recommendation_rows: int
    invalid_recommendation_rows: int
    missing_submission_time_rows: int
    missing_review_text_rows: int
    missing_review_title_rows: int
    duplicate_review_candidate_rows: int
    orphan_product_id_rows: int
    helpfulness_missing_rows: int
    helpfulness_invalid_rows: int
    invalid_feedback_count_rows: int
    rows_with_quality_issue: int
    rows_with_quality_issue_rate: float | None


def _has_table(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    table_name: str,
) -> bool:
    row = connection.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [schema, table_name],
    ).fetchone()
    return row is not None


def _fetch_single_row(
    database_path: Path,
    query: str,
    table_name: str,
) -> tuple:
    if not database_path.is_file():
        raise ReviewMetricsUnavailableError(
            f"Configured DuckDB file does not exist: {database_path}"
        )
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            schema, name = table_name.split(".", maxsplit=1)
            if not _has_table(connection, schema, name):
                raise ReviewMetricsUnavailableError(
                    f"Required Gold table {table_name} is unavailable."
                )
            rows = connection.execute(query).fetchall()
    except duckdb.Error as error:
        raise ReviewMetricsUnavailableError(
            f"Required Gold table {table_name} is unavailable or incompatible: {error}"
        ) from error
    if len(rows) != 1:
        raise ReviewMetricsUnavailableError(
            f"Required Gold table {table_name} must return exactly one row; "
            f"found {len(rows)}."
        )
    return rows[0]


def _fetch_rows(database_path: Path, query: str, table_name: str) -> list[tuple]:
    if not database_path.is_file():
        raise ReviewMetricsUnavailableError(
            f"Configured DuckDB file does not exist: {database_path}"
        )
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            schema, name = table_name.split(".", maxsplit=1)
            if not _has_table(connection, schema, name):
                raise ReviewMetricsUnavailableError(
                    f"Required Gold table {table_name} is unavailable."
                )
            rows = connection.execute(query).fetchall()
    except duckdb.Error as error:
        raise ReviewMetricsUnavailableError(
            f"Required Gold table {table_name} is unavailable or incompatible: {error}"
        ) from error
    return rows


def load_review_summary(database_path: Path) -> ReviewSummary:
    query = f"""
        SELECT
            total_review_rows,
            distinct_product_ids,
            valid_rating_rows,
            invalid_rating_rows,
            average_rating,
            median_rating,
            missing_product_id_rows,
            missing_rating_rows,
            missing_recommendation_rows,
            invalid_recommendation_rows,
            missing_submission_time_rows,
            missing_review_text_rows,
            missing_review_title_rows,
            duplicate_review_candidate_rows,
            orphan_product_id_rows,
            recommended_review_rows,
            not_recommended_review_rows,
            valid_recommendation_rows,
            recommendation_rate,
            helpfulness_review_rows,
            total_feedback_votes,
            positive_feedback_votes,
            negative_feedback_votes,
            helpfulness_missing_rows,
            helpfulness_invalid_rows,
            invalid_feedback_count_rows,
            average_helpfulness,
            weighted_helpfulness_rate,
            rows_with_quality_issue,
            rows_with_quality_issue_rate
        FROM {REVIEW_SUMMARY_TABLE}
    """
    row = _fetch_single_row(database_path, query, REVIEW_SUMMARY_TABLE)
    return ReviewSummary(
        total_review_rows=int(row[0]),
        distinct_product_ids=int(row[1]),
        valid_rating_rows=int(row[2]),
        invalid_rating_rows=int(row[3]),
        average_rating=float(row[4]) if row[4] is not None else None,
        median_rating=float(row[5]) if row[5] is not None else None,
        missing_product_id_rows=int(row[6]),
        missing_rating_rows=int(row[7]),
        missing_recommendation_rows=int(row[8]),
        invalid_recommendation_rows=int(row[9]),
        missing_submission_time_rows=int(row[10]),
        missing_review_text_rows=int(row[11]),
        missing_review_title_rows=int(row[12]),
        duplicate_review_candidate_rows=int(row[13]),
        orphan_product_id_rows=int(row[14]),
        recommended_review_rows=int(row[15]),
        not_recommended_review_rows=int(row[16]),
        valid_recommendation_rows=int(row[17]),
        recommendation_rate=float(row[18]) if row[18] is not None else None,
        helpfulness_review_rows=int(row[19]),
        total_feedback_votes=int(row[20]),
        positive_feedback_votes=int(row[21]),
        negative_feedback_votes=int(row[22]),
        helpfulness_missing_rows=int(row[23]),
        helpfulness_invalid_rows=int(row[24]),
        invalid_feedback_count_rows=int(row[25]),
        average_helpfulness=float(row[26]) if row[26] is not None else None,
        weighted_helpfulness_rate=(
            float(row[27]) if row[27] is not None else None
        ),
        rows_with_quality_issue=int(row[28]),
        rows_with_quality_issue_rate=(
            float(row[29]) if row[29] is not None else None
        ),
    )


def load_review_rating_distribution(
    database_path: Path,
) -> tuple[ReviewRatingBucket, ...]:
    query = f"""
        SELECT rating, review_rows, valid_rating_rows, share_of_valid_ratings
        FROM {REVIEW_RATING_TABLE}
        ORDER BY rating ASC NULLS LAST
    """
    rows = _fetch_rows(database_path, query, REVIEW_RATING_TABLE)
    return tuple(
        ReviewRatingBucket(
            rating=float(rating),
            review_rows=int(review_rows),
            valid_rating_rows=int(valid_rating_rows),
            share_of_valid_ratings=float(share) if share is not None else None,
        )
        for rating, review_rows, valid_rating_rows, share in rows
    )


def load_review_recommendation_summary(
    database_path: Path,
) -> ReviewRecommendationSummary:
    query = f"""
        SELECT
            recommended_review_rows,
            not_recommended_review_rows,
            missing_recommendation_rows,
            invalid_recommendation_rows,
            valid_recommendation_rows,
            recommendation_rate
        FROM {REVIEW_RECOMMENDATION_TABLE}
    """
    row = _fetch_single_row(database_path, query, REVIEW_RECOMMENDATION_TABLE)
    return ReviewRecommendationSummary(
        recommended_review_rows=int(row[0]),
        not_recommended_review_rows=int(row[1]),
        missing_recommendation_rows=int(row[2]),
        invalid_recommendation_rows=int(row[3]),
        valid_recommendation_rows=int(row[4]),
        recommendation_rate=float(row[5]) if row[5] is not None else None,
    )


def load_review_trends(database_path: Path) -> tuple[ReviewTrend, ...]:
    query = f"""
        SELECT
            strftime(month, '%Y-%m'),
            review_rows,
            valid_rating_rows,
            average_rating,
            valid_recommendation_rows,
            recommendation_rate
        FROM {REVIEW_TRENDS_TABLE}
        ORDER BY month ASC
    """
    rows = _fetch_rows(database_path, query, REVIEW_TRENDS_TABLE)
    return tuple(
        ReviewTrend(
            month=str(month),
            review_rows=int(review_rows),
            valid_rating_rows=int(valid_rating_rows),
            average_rating=float(avg_rating) if avg_rating is not None else None,
            valid_recommendation_rows=int(valid_recommendation_rows),
            recommendation_rate=float(rate) if rate is not None else None,
        )
        for (
            month,
            review_rows,
            valid_rating_rows,
            avg_rating,
            valid_recommendation_rows,
            rate,
        ) in rows
    )


def load_review_product_summary(
    database_path: Path,
) -> tuple[ReviewProductSummary, ...]:
    query = f"""
        SELECT
            product_id,
            product_name,
            review_rows,
            valid_rating_rows,
            average_rating,
            valid_recommendation_rows,
            recommendation_rate
        FROM {REVIEW_PRODUCT_TABLE}
        ORDER BY review_rows DESC, product_id NULLS LAST, product_name NULLS LAST
    """
    rows = _fetch_rows(database_path, query, REVIEW_PRODUCT_TABLE)
    return tuple(
        ReviewProductSummary(
            product_id=product_id,
            product_name=product_name,
            review_rows=int(review_rows),
            valid_rating_rows=int(valid_rating_rows),
            average_rating=float(avg_rating) if avg_rating is not None else None,
            valid_recommendation_rows=int(valid_recommendation_rows),
            recommendation_rate=float(rate) if rate is not None else None,
        )
        for (
            product_id,
            product_name,
            review_rows,
            valid_rating_rows,
            avg_rating,
            valid_recommendation_rows,
            rate,
        ) in rows
    )


def load_review_brand_summary(
    database_path: Path,
) -> tuple[ReviewBrandSummary, ...]:
    query = f"""
        SELECT
            brand_key,
            brand_name,
            review_rows,
            valid_rating_rows,
            average_rating,
            valid_recommendation_rows,
            recommendation_rate
        FROM {REVIEW_BRAND_TABLE}
        ORDER BY review_rows DESC, brand_key NULLS LAST, brand_name NULLS LAST
    """
    rows = _fetch_rows(database_path, query, REVIEW_BRAND_TABLE)
    return tuple(
        ReviewBrandSummary(
            brand_key=brand_key,
            brand_name=brand_name,
            review_rows=int(review_rows),
            valid_rating_rows=int(valid_rating_rows),
            average_rating=float(avg_rating) if avg_rating is not None else None,
            valid_recommendation_rows=int(valid_recommendation_rows),
            recommendation_rate=float(rate) if rate is not None else None,
        )
        for (
            brand_key,
            brand_name,
            review_rows,
            valid_rating_rows,
            avg_rating,
            valid_recommendation_rows,
            rate,
        ) in rows
    )


def load_review_category_summary(
    database_path: Path,
) -> tuple[ReviewCategorySummary, ...]:
    query = f"""
        SELECT
            category,
            review_rows,
            valid_rating_rows,
            average_rating,
            valid_recommendation_rows,
            recommendation_rate
        FROM {REVIEW_CATEGORY_TABLE}
        ORDER BY review_rows DESC, category NULLS LAST
    """
    rows = _fetch_rows(database_path, query, REVIEW_CATEGORY_TABLE)
    return tuple(
        ReviewCategorySummary(
            category=category,
            review_rows=int(review_rows),
            valid_rating_rows=int(valid_rating_rows),
            average_rating=float(avg_rating) if avg_rating is not None else None,
            valid_recommendation_rows=int(valid_recommendation_rows),
            recommendation_rate=float(rate) if rate is not None else None,
        )
        for (
            category,
            review_rows,
            valid_rating_rows,
            avg_rating,
            valid_recommendation_rows,
            rate,
        ) in rows
    )


def load_review_quality_summary(database_path: Path) -> ReviewQualitySummary:
    query = f"""
        SELECT
            total_review_rows,
            missing_product_id_rows,
            missing_rating_rows,
            invalid_rating_rows,
            missing_recommendation_rows,
            invalid_recommendation_rows,
            missing_submission_time_rows,
            missing_review_text_rows,
            missing_review_title_rows,
            duplicate_review_candidate_rows,
            orphan_product_id_rows,
            rows_with_quality_issue,
            rows_with_quality_issue_rate,
            helpfulness_missing_rows,
            helpfulness_invalid_rows,
            invalid_feedback_count_rows
        FROM {REVIEW_QUALITY_TABLE}
    """
    row = _fetch_single_row(database_path, query, REVIEW_QUALITY_TABLE)
    return ReviewQualitySummary(
        total_review_rows=int(row[0]),
        missing_product_id_rows=int(row[1]),
        missing_rating_rows=int(row[2]),
        invalid_rating_rows=int(row[3]),
        missing_recommendation_rows=int(row[4]),
        invalid_recommendation_rows=int(row[5]),
        missing_submission_time_rows=int(row[6]),
        missing_review_text_rows=int(row[7]),
        missing_review_title_rows=int(row[8]),
        duplicate_review_candidate_rows=int(row[9]),
        orphan_product_id_rows=int(row[10]),
        rows_with_quality_issue=int(row[11]),
        rows_with_quality_issue_rate=float(row[12]) if row[12] is not None else None,
        helpfulness_missing_rows=int(row[13]),
        helpfulness_invalid_rows=int(row[14]),
        invalid_feedback_count_rows=int(row[15]),
    )
