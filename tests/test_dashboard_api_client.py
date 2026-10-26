"""Unit tests for the dashboard API client."""

from __future__ import annotations

import httpx
import pytest

from dashboard.api_client import (
    APIClientError,
    APIConnectionError,
    APIStatusError,
    RetailEngineClient,
)


def test_api_client_initialization():
    client = RetailEngineClient(base_url="http://custom-host:9000/")
    assert client.base_url == "http://custom-host:9000"
    assert client.timeout == 8.0
    assert client.assistant_timeout == 35.0


def test_api_client_default_url(monkeypatch):
    monkeypatch.delenv("RETAIL_ENGINE_API_URL", raising=False)
    client = RetailEngineClient()
    assert client.base_url == "http://127.0.0.1:8000"

    monkeypatch.setenv("RETAIL_ENGINE_API_URL", "http://localhost:5000")
    client2 = RetailEngineClient()
    assert client2.base_url == "http://localhost:5000"


def test_api_client_get_success(monkeypatch):
    client = RetailEngineClient(base_url="http://mock-api")

    def mock_get(self, url, **kwargs):
        assert url == "http://mock-api/health"
        return httpx.Response(200, json={"status": "ready", "gold_table": "main.mart_product_catalog"})

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    result = client.get_health()
    assert result["status"] == "ready"
    assert result["gold_table"] == "main.mart_product_catalog"


def test_api_client_status_error(monkeypatch):
    client = RetailEngineClient(base_url="http://mock-api")

    def mock_get(self, url, **kwargs):
        return httpx.Response(503, json={"detail": "Mart unavailable"})

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    with pytest.raises(APIStatusError) as exc_info:
        client.get_review_summary()
    assert exc_info.value.status_code == 503
    assert "Mart unavailable" in exc_info.value.detail


def test_api_client_connection_error(monkeypatch):
    client = RetailEngineClient(base_url="http://unreachable-host:9999")

    def mock_get(self, url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    with pytest.raises(APIConnectionError) as exc_info:
        client.get_catalog_metrics()
    assert "Cannot connect to Retail Engine API" in str(exc_info.value)


def test_api_client_timeout_error(monkeypatch):
    client = RetailEngineClient(base_url="http://mock-api", timeout=1.0)

    def mock_get(self, url, **kwargs):
        raise httpx.ReadTimeout("Read timed out")

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    with pytest.raises(APIConnectionError) as exc_info:
        client.get_catalog_categories()
    assert "timed out after" in str(exc_info.value)


def test_api_client_ask_assistant_success(monkeypatch):
    client = RetailEngineClient(base_url="http://mock-api")

    def mock_post(self, url, *args, **kwargs):
        assert url == "http://mock-api/assistant/ask"
        json_body = kwargs.get("json", {})
        assert json_body["question"] == "What are categories?"
        return httpx.Response(
            200,
            json={
                "answer": "There are 9 categories.",
                "supported": True,
                "operation": "catalog_category_counts",
                "source_mart": "main.mart_catalog_by_category",
                "provider_status": "ok",
                "result": {"categories": []},
            },
        )

    monkeypatch.setattr(httpx.Client, "post", mock_post)
    resp = client.ask_assistant("What are categories?")
    assert resp["supported"] is True
    assert resp["operation"] == "catalog_category_counts"
    assert "9 categories" in resp["answer"]


def test_api_client_all_endpoint_wrappers_work(monkeypatch):
    """Verify that every endpoint method calls the expected URL path."""
    client = RetailEngineClient(base_url="http://mock-api")
    called_paths = []

    def mock_get(self, url, **kwargs):
        path = url.replace("http://mock-api", "")
        called_paths.append(path)
        return httpx.Response(200, json={"status": "ok", "mock": True})

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    client.get_catalog_metrics()
    client.get_catalog_categories()
    client.get_catalog_category_summary()
    client.get_catalog_brand_summary()
    client.get_catalog_quality_summary()
    client.get_review_summary()
    client.get_review_ratings()
    client.get_review_recommendations()
    client.get_review_trends()
    client.get_review_products()
    client.get_review_brands()
    client.get_review_categories()
    client.get_review_quality()

    expected_paths = [
        "/metrics/catalog",
        "/metrics/catalog/categories",
        "/metrics/catalog/category-summary",
        "/metrics/catalog/brands",
        "/metrics/catalog/quality",
        "/metrics/reviews",
        "/metrics/reviews/ratings",
        "/metrics/reviews/recommendations",
        "/metrics/reviews/trends",
        "/metrics/reviews/products",
        "/metrics/reviews/brands",
        "/metrics/reviews/categories",
        "/metrics/reviews/quality",
    ]
    assert called_paths == expected_paths
