from math import isclose
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from app.main import app
from src.analytics.review_metrics import (
    REVIEW_SUMMARY_TABLE,
    ReviewMetricsUnavailableError,
    load_review_summary,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REVIEW_MARTS = (
    "mart_review_summary",
    "mart_review_rating_distribution",
    "mart_review_recommendation_summary",
    "mart_review_monthly_trends",
    "mart_review_product_summary",
    "mart_review_brand_summary",
    "mart_review_category_summary",
    "mart_review_quality_summary",
)


def _materialize_model(
    connection: duckdb.DuckDBPyConnection,
    model_path: Path,
    relation: str,
    replacements: dict[str, str],
) -> None:
    sql = model_path.read_text(encoding="utf-8")
    sql = sql.replace("{{ config(materialized='table') }}", "")
    for template, resolved_relation in replacements.items():
        sql = sql.replace(template, resolved_relation)
    connection.execute(f"CREATE TABLE {relation} AS {sql}")


def _create_synthetic_review_marts(
    database_path: Path,
    *,
    include_review_rows: bool = True,
) -> None:
    model_dir = PROJECT_ROOT / "dbt_retail" / "model"
    with duckdb.connect(str(database_path)) as connection:
        connection.execute("CREATE SCHEMA raw")
        connection.execute(
            """
            CREATE TABLE raw.sephora_reviews (
                source_filename VARCHAR,
                product_id VARCHAR,
                rating VARCHAR,
                is_recommended VARCHAR,
                helpfulness VARCHAR,
                total_feedback_count VARCHAR,
                total_pos_feedback_count VARCHAR,
                total_neg_feedback_count VARCHAR,
                submission_time VARCHAR,
                review_text VARCHAR,
                review_title VARCHAR,
                author_id VARCHAR
            )
            """
        )
        review_rows = [
                (
                    "one.csv", "p1", "5", "1.0", "0.5", "2", "1", "1",
                    "2024-01-10", "good", "great", "a1",
                ),
                (
                    "two.csv", "p1", "5", "1.0", "0.5", "2", "1", "1",
                    "2024-01-10", "good", "great", "a1",
                ),
                (
                    "one.csv", "p2", "bad", "maybe", "0.9", "4", "2", "1",
                    "not-a-date", None, "", "a2",
                ),
                (
                    "one.csv", "orphan", "4", "false", "1.0", "1", "1", "0",
                    "2024-02-20", "okay", "fine", "a3",
                ),
                (
                    "one.csv", None, "", "", None, "0", "0", "0",
                    "", " ", None, "a4",
                ),
                (
                    "two.csv", "p2", "0", "false", None, "0", "0", "0",
                    "2024-02-21", "text", "title", "a5",
                ),
            ]
        if include_review_rows:
            connection.executemany(
                """
                INSERT INTO raw.sephora_reviews
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                review_rows,
            )
        connection.execute(
            """
            CREATE TABLE main.mart_product_catalog (
                product_id VARCHAR,
                product_name_standardized VARCHAR,
                brand_key VARCHAR,
                brand_standardized VARCHAR,
                category VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO main.mart_product_catalog VALUES (?, ?, ?, ?, ?)",
            [
                ("p1", "Product One", "brand-a", "Brand A", "skincare"),
                ("p2", "Product Two", "brand-b", "Brand B", "makeup"),
            ],
        )

        _materialize_model(
            connection,
            model_dir / "staging" / "stg_raw_reviews.sql",
            "main.stg_raw_reviews",
            {"{{ source('raw', 'sephora_reviews') }}": "raw.sephora_reviews"},
        )
        _materialize_model(
            connection,
            model_dir / "intermediate" / "int_review_analytics.sql",
            "main.int_review_analytics",
            {
                "{{ ref('mart_product_catalog') }}": "main.mart_product_catalog",
                "{{ ref('stg_raw_reviews') }}": "main.stg_raw_reviews",
            },
        )
        for mart in REVIEW_MARTS:
            _materialize_model(
                connection,
                model_dir / "marts" / f"{mart}.sql",
                f"main.{mart}",
                {"{{ ref('int_review_analytics') }}": "main.int_review_analytics"},
            )


def test_synthetic_review_models_and_all_api_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "review_fixture.duckdb"
    _create_synthetic_review_marts(database_path)
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))

    with TestClient(app) as client:
        responses = {
            endpoint: client.get(f"/metrics/reviews{endpoint}")
            for endpoint in (
                "",
                "/ratings",
                "/recommendations",
                "/trends",
                "/products",
                "/brands",
                "/categories",
                "/quality",
            )
        }

    assert all(response.status_code == 200 for response in responses.values())
    summary = responses[""].json()
    assert summary["total_review_rows"] == 6
    assert summary["distinct_product_ids"] == 3
    assert summary["valid_rating_rows"] == 3
    assert summary["invalid_rating_rows"] == 2
    assert isclose(summary["average_rating"], 14 / 3)
    assert summary["median_rating"] == 5.0
    assert summary["missing_product_id_rows"] == 1
    assert summary["missing_recommendation_rows"] == 1
    assert summary["invalid_recommendation_rows"] == 1
    assert summary["duplicate_review_candidate_rows"] == 2
    assert summary["orphan_product_id_rows"] == 1
    assert summary["recommended_review_rows"] == 2
    assert summary["not_recommended_review_rows"] == 2
    assert summary["valid_recommendation_rows"] == 4
    assert isclose(summary["recommendation_rate"], 0.5)
    assert summary["helpfulness_review_rows"] == 3
    assert summary["total_feedback_votes"] == 5
    assert summary["positive_feedback_votes"] == 3
    assert summary["negative_feedback_votes"] == 2
    assert summary["helpfulness_missing_rows"] == 0
    assert summary["helpfulness_invalid_rows"] == 1
    assert summary["invalid_feedback_count_rows"] == 1
    assert isclose(summary["average_helpfulness"], 2 / 3)
    assert isclose(summary["weighted_helpfulness_rate"], 3 / 5)

    ratings = responses["/ratings"].json()["ratings"]
    assert [(row["rating"], row["review_rows"]) for row in ratings] == [
        (4.0, 1),
        (5.0, 2),
    ]
    assert all(row["valid_rating_rows"] == 3 for row in ratings)

    recommendations = responses["/recommendations"].json()
    assert recommendations["valid_recommendation_rows"] == 4
    assert isclose(recommendations["recommendation_rate"], 0.5)

    trends = responses["/trends"].json()["trends"]
    assert [(row["month"], row["review_rows"]) for row in trends] == [
        ("2024-01", 2),
        ("2024-02", 2),
    ]

    products = responses["/products"].json()["products"]
    assert [(row["product_id"], row["review_rows"]) for row in products] == [
        ("p1", 2),
        ("p2", 2),
        ("orphan", 1),
        (None, 1),
    ]
    assert sum(row["review_rows"] for row in products) == 6
    assert sum(
        row["review_rows"] for row in responses["/brands"].json()["brands"]
    ) == 6
    assert sum(
        row["review_rows"] for row in responses["/categories"].json()["categories"]
    ) == 6

    quality = responses["/quality"].json()
    assert quality["total_review_rows"] == 6
    assert quality["rows_with_quality_issue"] == 6
    assert quality["rows_with_quality_issue_rate"] == 1.0
    assert quality["helpfulness_invalid_rows"] == 1
    assert all(
        "review_text" not in response.json()
        and "author_id" not in response.json()
        for response in responses.values()
    )


def test_review_summary_requires_exactly_one_gold_row(tmp_path: Path) -> None:
    database_path = tmp_path / "multiple_summary_rows.duckdb"
    _create_synthetic_review_marts(database_path)
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            f"INSERT INTO {REVIEW_SUMMARY_TABLE} SELECT * FROM {REVIEW_SUMMARY_TABLE}"
        )

    with pytest.raises(
        ReviewMetricsUnavailableError,
        match="must return exactly one row; found 2",
    ):
        load_review_summary(database_path)


def test_missing_review_mart_returns_service_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "missing_review_mart.duckdb"
    with duckdb.connect(str(database_path)):
        pass
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))

    with TestClient(app) as client:
        response = client.get("/metrics/reviews")

    assert response.status_code == 503
    assert REVIEW_SUMMARY_TABLE in response.json()["detail"]


def test_incompatible_review_mart_returns_service_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "incompatible_review_mart.duckdb"
    _create_synthetic_review_marts(database_path)
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            f"UPDATE {REVIEW_SUMMARY_TABLE} SET total_review_rows = -1"
        )
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))

    with TestClient(app) as client:
        response = client.get("/metrics/reviews")

    assert response.status_code == 503
    assert "incompatible with its response contract" in response.json()["detail"]


def test_empty_review_source_returns_null_rate_medians(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "empty_reviews.duckdb"
    _create_synthetic_review_marts(database_path, include_review_rows=False)
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))

    with TestClient(app) as client:
        response = client.get("/metrics/reviews")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_review_rows"] == 0
    assert payload["average_rating"] is None
    assert payload["median_rating"] is None
    assert payload["helpfulness_review_rows"] == 0
    assert payload["total_feedback_votes"] == 0
    assert payload["average_helpfulness"] is None
    assert payload["weighted_helpfulness_rate"] is None
    assert payload["rows_with_quality_issue_rate"] is None
