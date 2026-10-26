from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from app.main import app
from src.ai.assistant_service import GroqAnalyticsService


def _create_minimal_metric_fixture(database_path: str) -> None:
    with duckdb.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE main.mart_product_catalog (
                product_id VARCHAR,
                product_name_standardized VARCHAR,
                brand_key VARCHAR,
                brand_standardized VARCHAR,
                category VARCHAR,
                category_missing BOOLEAN,
                duplicate_product_id BOOLEAN,
                duplicate_brand_name_candidate BOOLEAN,
                ingredients_text_missing BOOLEAN,
                product_price_invalid BOOLEAN,
                product_rating_invalid BOOLEAN,
                aggregate_review_count_invalid BOOLEAN,
                loves_count_invalid BOOLEAN
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO main.mart_product_catalog (
                product_id,
                product_name_standardized,
                brand_key,
                brand_standardized,
                category,
                category_missing,
                duplicate_product_id,
                duplicate_brand_name_candidate,
                ingredients_text_missing,
                product_price_invalid,
                product_rating_invalid,
                aggregate_review_count_invalid,
                loves_count_invalid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("p1", "Product One", "brand-a", "Brand A", "skincare", False, False, False, False, False, False, False, False),
                ("p2", "Product Two", "brand-b", "Brand B", "makeup", False, False, False, False, False, False, False, False),
                ("p3", "Product Three", "brand-c", "Brand C", None, True, False, False, False, False, False, False, False),
            ],
        )

        connection.execute(
            """
            CREATE TABLE main.mart_review_summary (
                total_review_rows BIGINT,
                distinct_product_ids BIGINT,
                valid_rating_rows BIGINT,
                invalid_rating_rows BIGINT,
                average_rating DOUBLE,
                median_rating DOUBLE,
                missing_product_id_rows BIGINT,
                missing_rating_rows BIGINT,
                missing_recommendation_rows BIGINT,
                invalid_recommendation_rows BIGINT,
                missing_submission_time_rows BIGINT,
                missing_review_text_rows BIGINT,
                missing_review_title_rows BIGINT,
                duplicate_review_candidate_rows BIGINT,
                orphan_product_id_rows BIGINT,
                recommended_review_rows BIGINT,
                not_recommended_review_rows BIGINT,
                valid_recommendation_rows BIGINT,
                recommendation_rate DOUBLE,
                helpfulness_review_rows BIGINT,
                total_feedback_votes BIGINT,
                positive_feedback_votes BIGINT,
                negative_feedback_votes BIGINT,
                helpfulness_missing_rows BIGINT,
                helpfulness_invalid_rows BIGINT,
                invalid_feedback_count_rows BIGINT,
                average_helpfulness DOUBLE,
                weighted_helpfulness_rate DOUBLE,
                rows_with_quality_issue BIGINT,
                rows_with_quality_issue_rate DOUBLE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO main.mart_review_summary VALUES (
                42, 3, 35, 7, 4.5, 5.0,
                2, 3, 4, 2, 1, 5, 6,
                3, 1, 21, 14, 35, 0.6,
                31, 150, 120, 30, 4, 2, 3,
                0.75, 0.8, 9, 0.21428571428571427
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE main.mart_review_rating_distribution (
                rating DOUBLE,
                review_rows BIGINT,
                valid_rating_rows BIGINT,
                share_of_valid_ratings DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO main.mart_review_rating_distribution VALUES (?, ?, ?, ?)",
            [(1.0, 9, 9, 0.25), (5.0, 26, 26, 0.75)],
        )

        connection.execute(
            """
            CREATE TABLE main.mart_review_recommendation_summary (
                recommended_review_rows BIGINT,
                not_recommended_review_rows BIGINT,
                missing_recommendation_rows BIGINT,
                invalid_recommendation_rows BIGINT,
                valid_recommendation_rows BIGINT,
                recommendation_rate DOUBLE
            )
            """
        )
        connection.execute(
            "INSERT INTO main.mart_review_recommendation_summary VALUES (21, 14, 4, 2, 35, 0.6)"
        )

        connection.execute(
            """
            CREATE TABLE main.mart_review_monthly_trends (
                month DATE,
                review_rows BIGINT,
                valid_rating_rows BIGINT,
                average_rating DOUBLE,
                valid_recommendation_rows BIGINT,
                recommendation_rate DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO main.mart_review_monthly_trends VALUES (?, ?, ?, ?, ?, ?)",
            [("2024-01-01", 18, 16, 4.7, 15, 0.67), ("2024-02-01", 24, 19, 4.3, 20, 0.55)],
        )

        connection.execute(
            """
            CREATE TABLE main.mart_review_product_summary (
                product_id VARCHAR,
                product_name VARCHAR,
                review_rows BIGINT,
                valid_rating_rows BIGINT,
                average_rating DOUBLE,
                valid_recommendation_rows BIGINT,
                recommendation_rate DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO main.mart_review_product_summary VALUES (?, ?, ?, ?, ?, ?, ?)",
            [("p1", "Product One", 16, 15, 4.6, 14, 0.7), ("p2", "Product Two", 12, 12, 4.4, 11, 0.6)],
        )

        connection.execute(
            """
            CREATE TABLE main.mart_review_brand_summary (
                brand_key VARCHAR,
                brand_name VARCHAR,
                review_rows BIGINT,
                valid_rating_rows BIGINT,
                average_rating DOUBLE,
                valid_recommendation_rows BIGINT,
                recommendation_rate DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO main.mart_review_brand_summary VALUES (?, ?, ?, ?, ?, ?, ?)",
            [("brand-a", "Brand A", 20, 18, 4.8, 17, 0.72), ("brand-b", "Brand B", 22, 17, 4.2, 18, 0.58)],
        )

        connection.execute(
            """
            CREATE TABLE main.mart_review_category_summary (
                category VARCHAR,
                review_rows BIGINT,
                valid_rating_rows BIGINT,
                average_rating DOUBLE,
                valid_recommendation_rows BIGINT,
                recommendation_rate DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO main.mart_review_category_summary VALUES (?, ?, ?, ?, ?, ?)",
            [("skincare", 21, 19, 4.6, 18, 0.7), ("makeup", 21, 16, 4.1, 17, 0.6)],
        )

        connection.execute(
            """
            CREATE TABLE main.mart_review_quality_summary (
                total_review_rows BIGINT,
                missing_product_id_rows BIGINT,
                missing_rating_rows BIGINT,
                invalid_rating_rows BIGINT,
                missing_recommendation_rows BIGINT,
                invalid_recommendation_rows BIGINT,
                missing_submission_time_rows BIGINT,
                missing_review_text_rows BIGINT,
                missing_review_title_rows BIGINT,
                duplicate_review_candidate_rows BIGINT,
                orphan_product_id_rows BIGINT,
                helpfulness_missing_rows BIGINT,
                helpfulness_invalid_rows BIGINT,
                invalid_feedback_count_rows BIGINT,
                rows_with_quality_issue BIGINT,
                rows_with_quality_issue_rate DOUBLE
            )
            """
        )
        connection.execute(
            "INSERT INTO main.mart_review_quality_summary VALUES (42, 2, 3, 7, 4, 2, 1, 5, 6, 3, 1, 4, 2, 3, 9, 0.21428571428571427)"
        )


def test_supported_question_routes_to_allowed_operation(monkeypatch, tmp_path):
    database_path = tmp_path / "nl_fixture.duckdb"
    _create_minimal_metric_fixture(str(database_path))
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    service = GroqAnalyticsService()
    response = service.ask("Give me the overall review summary.")
    assert response.operation == "review_summary"
    assert response.supported is True
    assert response.result["total_review_rows"] == 42
    assert response.provider_status == "missing_key"

    unsupported = service.ask("What is my revenue and profit forecast?")
    assert unsupported.operation is None
    assert unsupported.supported is False
    assert unsupported.provider_status == "unsupported_question"


def test_groq_timeout_and_retry_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("GROQ_MAX_RETRIES", "4")

    service = GroqAnalyticsService()

    assert service.timeout_seconds == 12.5
    assert service.max_retries == 4


@pytest.mark.parametrize(
    ("environment", "value", "message"),
    [
        ("GROQ_TIMEOUT_SECONDS", "0", "positive number"),
        ("GROQ_TIMEOUT_SECONDS", "invalid", "positive number"),
        ("GROQ_TIMEOUT_SECONDS", "nan", "positive number"),
        ("GROQ_MAX_RETRIES", "-1", "non-negative integer"),
        ("GROQ_MAX_RETRIES", "invalid", "non-negative integer"),
    ],
)
def test_invalid_groq_settings_raise_clear_configuration_error(
    monkeypatch, environment, value, message
):
    monkeypatch.setenv(environment, value)

    with pytest.raises(ValueError, match=message):
        GroqAnalyticsService()


def test_assistant_route_returns_mocked_provider_result(monkeypatch, tmp_path):
    database_path = tmp_path / "nl_fixture.duckdb"
    _create_minimal_metric_fixture(str(database_path))
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def fake_call(self, *, prompt: str, tools: list[dict], operation_hint: str | None = None):
        return {"name": "catalog_summary", "arguments": {"max_results": 10}}

    monkeypatch.setattr(GroqAnalyticsService, "_call_provider", fake_call)

    with TestClient(app) as client:
        response = client.post(
            "/assistant/ask",
            json={"question": "Describe the product catalog summary.", "max_results": 10},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"] == "catalog_summary"
    assert payload["supported"] is True
    assert payload["result"]["total_products"] == 3
    assert payload["provider_status"] == "ok"


def test_missing_key_returns_503(monkeypatch, tmp_path):
    database_path = tmp_path / "nl_fixture.duckdb"
    _create_minimal_metric_fixture(str(database_path))
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with TestClient(app) as client:
        response = client.post(
            "/assistant/ask",
            json={"question": "How many products are in the catalog?"},
        )
    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]


def test_invalid_groq_configuration_returns_503(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "0")

    with TestClient(app) as client:
        response = client.post(
            "/assistant/ask",
            json={"question": "How many products are in the catalog?"},
        )

    assert response.status_code == 503
    assert "GROQ_TIMEOUT_SECONDS" in response.json()["detail"]


def test_provider_failure_after_success_returns_fallback(monkeypatch, tmp_path):
    database_path = tmp_path / "nl_fixture.duckdb"
    _create_minimal_metric_fixture(str(database_path))
    monkeypatch.setenv("RETAIL_ENGINE_DB_PATH", str(database_path))
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def fake_call(self, *, prompt: str, tools: list[dict], operation_hint: str | None = None):
        raise ValueError("Malformed Groq response")

    monkeypatch.setattr(GroqAnalyticsService, "_call_provider", fake_call)

    service = GroqAnalyticsService()
    response = service.ask("What are the review ratings?")
    assert response.operation == "review_rating_distribution"
    assert response.supported is True
    assert response.provider_status == "provider_error"
    assert response.result["ratings"][0]["rating"] == 1.0
    assert "rating" in response.answer.lower()
