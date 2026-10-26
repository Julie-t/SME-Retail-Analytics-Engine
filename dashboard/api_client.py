"""Typed API Client for interacting with the Deterministic SME Retail Analytics Engine backend."""

from __future__ import annotations

import os
from typing import Any
import httpx


class APIClientError(Exception):
    """Base exception for dashboard API client errors."""


class APIConnectionError(APIClientError):
    """Raised when the API is unreachable, refused connection, or timed out."""


class APIStatusError(APIClientError):
    """Raised when the API returns an HTTP 4xx or 5xx status code."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"API Error ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


class RetailEngineClient:
    """HTTP client that consumes the existing FastAPI endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 8.0,
        assistant_timeout: float = 35.0,
    ) -> None:
        self.base_url = (
            base_url
            if base_url is not None
            else os.environ.get("RETAIL_ENGINE_API_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        self.timeout = timeout
        self.assistant_timeout = assistant_timeout

    def _get(self, path: str, timeout: float | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        effective_timeout = timeout if timeout is not None else self.timeout
        try:
            with httpx.Client(timeout=effective_timeout) as client:
                response = client.get(url)
                if response.status_code != 200:
                    try:
                        detail = response.json().get("detail", response.text)
                    except Exception:
                        detail = response.text
                    raise APIStatusError(response.status_code, str(detail))
                return response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
            raise APIConnectionError(
                f"Cannot connect to Retail Engine API at {self.base_url}. "
                "Ensure the Uvicorn server is running on loopback."
            ) from exc
        except httpx.ReadTimeout as exc:
            raise APIConnectionError(
                f"Request to {path} timed out after {effective_timeout}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise APIClientError(f"HTTP communication error on {path}: {exc}") from exc

    def _post(self, path: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        effective_timeout = timeout if timeout is not None else self.assistant_timeout
        try:
            with httpx.Client(timeout=effective_timeout) as client:
                response = client.post(url, json=payload)
                if response.status_code != 200:
                    try:
                        detail = response.json().get("detail", response.text)
                    except Exception:
                        detail = response.text
                    raise APIStatusError(response.status_code, str(detail))
                return response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
            raise APIConnectionError(
                f"Cannot connect to Retail Engine API at {self.base_url}. "
                "Ensure the Uvicorn server is running on loopback."
            ) from exc
        except httpx.ReadTimeout as exc:
            raise APIConnectionError(
                f"Assistant request timed out after {effective_timeout}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise APIClientError(f"HTTP communication error on {path}: {exc}") from exc

    # System Health
    def get_health(self) -> dict[str, Any]:
        """Check API service and Gold database readiness."""
        return self._get("/health", timeout=3.0)

    # Catalogue Metrics
    def get_catalog_metrics(self) -> dict[str, Any]:
        """Return product count, category counts, and high-level quality flags."""
        return self._get("/metrics/catalog")

    def get_catalog_categories(self) -> dict[str, Any]:
        """Return product counts grouped by primary canonical category."""
        return self._get("/metrics/catalog/categories")

    def get_catalog_category_summary(self) -> dict[str, Any]:
        """Return category counts and percentage shares from mart_catalog_by_category."""
        return self._get("/metrics/catalog/category-summary")

    def get_catalog_brand_summary(self) -> dict[str, Any]:
        """Return product counts and shares by brand from mart_catalog_by_brand."""
        return self._get("/metrics/catalog/brands")

    def get_catalog_quality_summary(self) -> dict[str, Any]:
        """Return full 31-metric product catalogue quality diagnostics."""
        return self._get("/metrics/catalog/quality")

    # Review Analytics
    def get_review_summary(self) -> dict[str, Any]:
        """Return overall review totals, ratings, recommendations, and helpfulness."""
        return self._get("/metrics/reviews")

    def get_review_ratings(self) -> dict[str, Any]:
        """Return 1-to-5 star rating distribution and shares from mart_review_rating_distribution."""
        return self._get("/metrics/reviews/ratings")

    def get_review_recommendations(self) -> dict[str, Any]:
        """Return recommendation totals, valid denominator, and recommendation rate."""
        return self._get("/metrics/reviews/recommendations")

    def get_review_trends(self) -> dict[str, Any]:
        """Return monthly review counts, ratings, and recommendation rates across 176 months."""
        return self._get("/metrics/reviews/trends")

    def get_review_products(self) -> dict[str, Any]:
        """Return review metrics for all 2,351 reviewed products."""
        return self._get("/metrics/reviews/products")

    def get_review_brands(self) -> dict[str, Any]:
        """Return review metrics for all 142 reviewed brands."""
        return self._get("/metrics/reviews/brands")

    def get_review_categories(self) -> dict[str, Any]:
        """Return category-grain review metrics from mart_review_category_summary."""
        return self._get("/metrics/reviews/categories")

    def get_review_quality(self) -> dict[str, Any]:
        """Return review quality diagnostics and issue rates from mart_review_quality_summary."""
        return self._get("/metrics/reviews/quality")

    # AI Retail Analyst (Assistant)
    def ask_assistant(self, question: str, max_results: int = 10) -> dict[str, Any]:
        """Ask a natural-language question grounded in deterministic analytics."""
        return self._post(
            "/assistant/ask",
            payload={"question": question, "max_results": max_results},
        )
