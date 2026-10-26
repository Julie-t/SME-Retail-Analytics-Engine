from __future__ import annotations

import json
import math
import os
import re
import time
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

try:
    from groq import Groq
except ImportError:  # pragma: no cover - this is handled in tests and runtime config
    Groq = None

from src.analytics.catalog_metrics import (
    load_catalog_brand_counts,
    load_catalog_category_summary,
    load_catalog_metrics,
    load_catalog_quality_summary,
)
from src.analytics.review_metrics import (
    load_review_brand_summary,
    load_review_category_summary,
    load_review_product_summary,
    load_review_quality_summary,
    load_review_rating_distribution,
    load_review_recommendation_summary,
    load_review_summary,
    load_review_trends,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "retail_engine.duckdb"


class UnsupportedQuestionError(ValueError):
    """Raised when the question cannot be mapped to an allowlisted metric."""


class MissingGroqAPIKeyError(RuntimeError):
    """Raised when the Groq provider is not configured."""


class ProviderFailure(RuntimeError):
    """Raised when the Groq provider cannot answer after calculation."""


class AnalyticsOperation(str, Enum):
    CATALOG_SUMMARY = "catalog_summary"
    CATALOG_CATEGORY_COUNTS = "catalog_category_counts"
    CATALOG_BRAND_COUNTS = "catalog_brand_counts"
    CATALOG_QUALITY_SUMMARY = "catalog_quality_summary"
    REVIEW_SUMMARY = "review_summary"
    REVIEW_RATING_DISTRIBUTION = "review_rating_distribution"
    REVIEW_RECOMMENDATION_SUMMARY = "review_recommendation_summary"
    REVIEW_TRENDS = "review_trends"
    REVIEW_PRODUCTS = "review_products"
    REVIEW_BRANDS = "review_brands"
    REVIEW_CATEGORIES = "review_categories"
    REVIEW_QUALITY_SUMMARY = "review_quality_summary"


class AssistantAskRequest(BaseModel):
    model_config = {"frozen": True}

    question: str = Field(..., min_length=3, max_length=2000)
    max_results: int = Field(default=10, ge=1, le=20)


class AssistantAnalyticsResponse(BaseModel):
    model_config = {"frozen": True}

    answer: str
    operation: str | None
    supported: bool
    result: dict[str, Any] | None = None
    filters: dict[str, Any] | None = None
    metric_definition: str | None = None
    source_mart: str | None = None
    provider_status: Literal[
        "ok",
        "missing_key",
        "rate_limit",
        "timeout",
        "malformed_response",
        "provider_error",
        "unsupported_question",
    ]
    reason: str | None = None


def _coerce_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _coerce_jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _coerce_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _tool_definition(
    name: str,
    description: str,
    properties: dict[str, dict[str, Any]],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


ANALYTICS_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _tool_definition(
        AnalyticsOperation.CATALOG_SUMMARY.value,
        "Return the overall catalog summary, including total products and quality diagnostics.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.CATALOG_CATEGORY_COUNTS.value,
        "Return product counts grouped by normalized category.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.CATALOG_BRAND_COUNTS.value,
        "Return product counts grouped by normalized brand.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.CATALOG_QUALITY_SUMMARY.value,
        "Return product catalog quality diagnostics and issue rates.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.REVIEW_SUMMARY.value,
        "Return the overall review summary, ratings, recommendation rates, and issue counts.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.REVIEW_RATING_DISTRIBUTION.value,
        "Return the distribution of valid review ratings from 1 to 5.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.REVIEW_RECOMMENDATION_SUMMARY.value,
        "Return recommendation counts and the valid recommendation rate.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.REVIEW_TRENDS.value,
        "Return review counts and rates aggregated by month.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.REVIEW_PRODUCTS.value,
        "Return per-product review counts and aggregate metrics.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.REVIEW_BRANDS.value,
        "Return review metrics by normalized brand.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.REVIEW_CATEGORIES.value,
        "Return review metrics by product category.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
    _tool_definition(
        AnalyticsOperation.REVIEW_QUALITY_SUMMARY.value,
        "Return review quality diagnostics and issue rates.",
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
    ),
]


OPERATION_METRIC_DEFINITIONS: dict[str, str] = {
    AnalyticsOperation.CATALOG_SUMMARY.value: (
        "Total products and quality diagnostics from main.mart_product_catalog. "
        "The product count is the catalog grain; quality rates use all catalog rows as the denominator."
    ),
    AnalyticsOperation.CATALOG_CATEGORY_COUNTS.value: (
        "Category bucket counts from main.mart_product_catalog. Missing categories remain a visible bucket."
    ),
    AnalyticsOperation.CATALOG_BRAND_COUNTS.value: (
        "Normalized brand counts from main.mart_product_catalog. The row count is the total product rows in each brand bucket."
    ),
    AnalyticsOperation.CATALOG_QUALITY_SUMMARY.value: (
        "Catalog quality summary from main.mart_product_catalog. Each rate uses the full catalog row count as the denominator, unless the metric is explicitly null for an empty table."
    ),
    AnalyticsOperation.REVIEW_SUMMARY.value: (
        "Review summary from main.mart_review_summary. Mean and median ratings use valid 1-to-5 ratings; recommendation rate divides valid positive recommendations by valid recommendation rows."
    ),
    AnalyticsOperation.REVIEW_RATING_DISTRIBUTION.value: (
        "Rating bucket distribution from main.mart_review_rating_distribution. Each bucket shares valid 1-to-5 ratings."
    ),
    AnalyticsOperation.REVIEW_RECOMMENDATION_SUMMARY.value: (
        "Recommendation summary from main.mart_review_recommendation_summary. The valid recommendation denominator excludes missing and invalid values."
    ),
    AnalyticsOperation.REVIEW_TRENDS.value: (
        "Monthly review trends from main.mart_review_monthly_trends. Review rows count all dated reviews; average rating and recommendation rate use their valid denominators."
    ),
    AnalyticsOperation.REVIEW_PRODUCTS.value: (
        "Per-product review rollup from main.mart_review_product_summary. Review rows are counted per product, with stable ordering by count and ID."
    ),
    AnalyticsOperation.REVIEW_BRANDS.value: (
        "Brand-level review rollup from main.mart_review_brand_summary. Missing brand rows remain in the output when present."
    ),
    AnalyticsOperation.REVIEW_CATEGORIES.value: (
        "Category-level review rollup from main.mart_review_category_summary. Missing category rows remain in the output when present."
    ),
    AnalyticsOperation.REVIEW_QUALITY_SUMMARY.value: (
        "Review quality summary from main.mart_review_quality_summary. Issue rates use the full review row count as the denominator."
    ),
}

SOURCE_MARTS: dict[str, str] = {
    AnalyticsOperation.CATALOG_SUMMARY.value: "main.mart_product_catalog",
    AnalyticsOperation.CATALOG_CATEGORY_COUNTS.value: "main.mart_product_catalog",
    AnalyticsOperation.CATALOG_BRAND_COUNTS.value: "main.mart_product_catalog",
    AnalyticsOperation.CATALOG_QUALITY_SUMMARY.value: "main.mart_product_catalog",
    AnalyticsOperation.REVIEW_SUMMARY.value: "main.mart_review_summary",
    AnalyticsOperation.REVIEW_RATING_DISTRIBUTION.value: "main.mart_review_rating_distribution",
    AnalyticsOperation.REVIEW_RECOMMENDATION_SUMMARY.value: "main.mart_review_recommendation_summary",
    AnalyticsOperation.REVIEW_TRENDS.value: "main.mart_review_monthly_trends",
    AnalyticsOperation.REVIEW_PRODUCTS.value: "main.mart_review_product_summary",
    AnalyticsOperation.REVIEW_BRANDS.value: "main.mart_review_brand_summary",
    AnalyticsOperation.REVIEW_CATEGORIES.value: "main.mart_review_category_summary",
    AnalyticsOperation.REVIEW_QUALITY_SUMMARY.value: "main.mart_review_quality_summary",
}


def _normalize_question(question: str) -> str:
    text = question.strip()
    if not text:
        raise UnsupportedQuestionError("Question is empty.")
    lowered = text.lower()
    if re.search(r"ignore\s+(?:all\s+)?instructions|system\s+prompt|drop\s+table|delete\s+from|union\s+select|os\.system|subprocess|sql\s*;|select\s+\*\s+from", lowered):
        raise UnsupportedQuestionError("Prompt injection or unsafe SQL request rejected.")
    return text


def _choose_operation(question: str) -> str | None:
    text = question.lower()
    if any(keyword in text for keyword in ["category", "categories"]) and "review" not in text:
        if any(keyword in text for keyword in ["count", "counts", "summary", "breakdown"]):
            return AnalyticsOperation.CATALOG_CATEGORY_COUNTS.value
    if any(keyword in text for keyword in ["brand", "brands"]) and "review" not in text:
        if any(keyword in text for keyword in ["count", "counts", "summary", "breakdown"]):
            return AnalyticsOperation.CATALOG_BRAND_COUNTS.value
    if any(keyword in text for keyword in ["catalog", "products", "product"]) and any(keyword in text for keyword in ["quality", "missing", "invalid", "issue", "duplicate"]):
        return AnalyticsOperation.CATALOG_QUALITY_SUMMARY.value
    if any(keyword in text for keyword in ["catalog", "product count", "product inventory", "catalog summary", "total products"]):
        return AnalyticsOperation.CATALOG_SUMMARY.value
    if any(keyword in text for keyword in ["review summary", "overall review", "review metrics"]) or ("review" in text and any(keyword in text for keyword in ["summary", "total", "overall"])):
        return AnalyticsOperation.REVIEW_SUMMARY.value
    if "review" in text and any(keyword in text for keyword in ["rating", "ratings", "distribution"]):
        return AnalyticsOperation.REVIEW_RATING_DISTRIBUTION.value
    if "review" in text and any(keyword in text for keyword in ["recommendation", "recommended", "not recommended"]):
        return AnalyticsOperation.REVIEW_RECOMMENDATION_SUMMARY.value
    if "review" in text and any(keyword in text for keyword in ["trend", "month", "monthly"]):
        return AnalyticsOperation.REVIEW_TRENDS.value
    if "review" in text and any(keyword in text for keyword in ["product", "products"]):
        return AnalyticsOperation.REVIEW_PRODUCTS.value
    if "review" in text and any(keyword in text for keyword in ["brand", "brands"]):
        return AnalyticsOperation.REVIEW_BRANDS.value
    if "review" in text and any(keyword in text for keyword in ["category", "categories"]):
        return AnalyticsOperation.REVIEW_CATEGORIES.value
    if "review" in text and any(keyword in text for keyword in ["quality", "issues", "duplicates", "missing"]):
        return AnalyticsOperation.REVIEW_QUALITY_SUMMARY.value
    if "catalog" in text and any(keyword in text for keyword in ["quality", "data quality", "issue"]):
        return AnalyticsOperation.CATALOG_QUALITY_SUMMARY.value
    return None


def _limit_items(items: Any, limit: int) -> Any:
    if isinstance(items, list):
        return items[:limit]
    return items


def _execute_catalog_summary(database_path: Path, max_results: int) -> dict[str, Any]:
    summary = load_catalog_metrics(database_path)
    payload = _coerce_jsonable(summary)
    payload["category_counts"] = _limit_items(payload.get("category_counts", []), max_results)
    return payload


def _execute_catalog_category_counts(database_path: Path, max_results: int) -> dict[str, Any]:
    summary = load_catalog_metrics(database_path)
    payload = _coerce_jsonable(summary)
    counts = payload.get("category_counts", [])
    return {"category_counts": _limit_items(counts, max_results)}


def _execute_catalog_brand_counts(database_path: Path, max_results: int) -> dict[str, Any]:
    brands = load_catalog_brand_counts(database_path)
    payload = {"brands": _limit_items(_coerce_jsonable(brands), max_results)}
    return payload


def _execute_catalog_quality_summary(database_path: Path, max_results: int) -> dict[str, Any]:
    summary = load_catalog_quality_summary(database_path)
    return _coerce_jsonable(summary)


def _execute_review_summary(database_path: Path, max_results: int) -> dict[str, Any]:
    summary = load_review_summary(database_path)
    return _coerce_jsonable(summary)


def _execute_review_rating_distribution(database_path: Path, max_results: int) -> dict[str, Any]:
    buckets = load_review_rating_distribution(database_path)
    return {"ratings": _limit_items(_coerce_jsonable(buckets), max_results)}


def _execute_review_recommendation_summary(database_path: Path, max_results: int) -> dict[str, Any]:
    summary = load_review_recommendation_summary(database_path)
    return _coerce_jsonable(summary)


def _execute_review_trends(database_path: Path, max_results: int) -> dict[str, Any]:
    trends = load_review_trends(database_path)
    return {"trends": _limit_items(_coerce_jsonable(trends), max_results)}


def _execute_review_products(database_path: Path, max_results: int) -> dict[str, Any]:
    products = load_review_product_summary(database_path)
    return {"products": _limit_items(_coerce_jsonable(products), max_results)}


def _execute_review_brands(database_path: Path, max_results: int) -> dict[str, Any]:
    brands = load_review_brand_summary(database_path)
    return {"brands": _limit_items(_coerce_jsonable(brands), max_results)}


def _execute_review_categories(database_path: Path, max_results: int) -> dict[str, Any]:
    categories = load_review_category_summary(database_path)
    return {"categories": _limit_items(_coerce_jsonable(categories), max_results)}


def _execute_review_quality_summary(database_path: Path, max_results: int) -> dict[str, Any]:
    summary = load_review_quality_summary(database_path)
    return _coerce_jsonable(summary)


OPERATION_EXECUTORS: dict[str, Any] = {
    AnalyticsOperation.CATALOG_SUMMARY.value: _execute_catalog_summary,
    AnalyticsOperation.CATALOG_CATEGORY_COUNTS.value: _execute_catalog_category_counts,
    AnalyticsOperation.CATALOG_BRAND_COUNTS.value: _execute_catalog_brand_counts,
    AnalyticsOperation.CATALOG_QUALITY_SUMMARY.value: _execute_catalog_quality_summary,
    AnalyticsOperation.REVIEW_SUMMARY.value: _execute_review_summary,
    AnalyticsOperation.REVIEW_RATING_DISTRIBUTION.value: _execute_review_rating_distribution,
    AnalyticsOperation.REVIEW_RECOMMENDATION_SUMMARY.value: _execute_review_recommendation_summary,
    AnalyticsOperation.REVIEW_TRENDS.value: _execute_review_trends,
    AnalyticsOperation.REVIEW_PRODUCTS.value: _execute_review_products,
    AnalyticsOperation.REVIEW_BRANDS.value: _execute_review_brands,
    AnalyticsOperation.REVIEW_CATEGORIES.value: _execute_review_categories,
    AnalyticsOperation.REVIEW_QUALITY_SUMMARY.value: _execute_review_quality_summary,
}


def get_database_path() -> Path:
    configured = os.environ.get("RETAIL_ENGINE_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_DATABASE_PATH

def _sanitize_error_message(message: str, api_key: str | None = None) -> str:
    cleaned = message
    if api_key and api_key in cleaned:
        cleaned = cleaned.replace(api_key, "[REDACTED]")
    cleaned = re.sub(r"gsk_[A-Za-z0-9_-]{20,}", "[REDACTED]", cleaned)
    return cleaned


class GroqAnalyticsService:
    """Groq-backed natural-language assistant that stays grounded in deterministic metrics."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("GROQ_API_KEY")
        self.model = model if model is not None else os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        configured_timeout = os.environ.get("GROQ_TIMEOUT_SECONDS", "30")
        configured_retries = os.environ.get("GROQ_MAX_RETRIES", "2")
        try:
            self.timeout_seconds = (
                timeout_seconds if timeout_seconds is not None else float(configured_timeout)
            )
        except ValueError as exc:
            raise ValueError("GROQ_TIMEOUT_SECONDS must be a positive number.") from exc
        try:
            self.max_retries = (
                max_retries if max_retries is not None else int(configured_retries)
            )
        except ValueError as exc:
            raise ValueError("GROQ_MAX_RETRIES must be a non-negative integer.") from exc
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("GROQ_TIMEOUT_SECONDS must be a positive number.")
        if self.max_retries < 0:
            raise ValueError("GROQ_MAX_RETRIES must be a non-negative integer.")

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("GROQ_API_KEY"))

    def _call_provider(self, *, prompt: str, tools: list[dict[str, Any]], operation_hint: str | None = None) -> Any:
        if not self.api_key:
            raise MissingGroqAPIKeyError("GROQ_API_KEY is not configured.")
        if Groq is None:
            raise ProviderFailure("Groq Python client is not installed.")

        client = Groq(api_key=self.api_key, timeout=self.timeout_seconds, max_retries=self.max_retries)
        payload = [
            {
                "role": "system",
                "content": (
                    "You are a strict analytics router. Choose one allowlisted analytics tool only. "
                    "Do not fabricate numeric results, do not use SQL, and never request unsupported business metrics."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        response = client.chat.completions.create(
            model=self.model,
            temperature=0.0,
            messages=payload,
            tools=tools,
            tool_choice="required",
        )
        message = response.choices[0].message
        if not getattr(message, "tool_calls", None):
            raise ProviderFailure("Groq response did not include a tool call.")
        tool_call = message.tool_calls[0]
        fn = getattr(tool_call, "function", None)
        if fn is None:
            raise ProviderFailure("Groq tool call is malformed.")
        name = getattr(fn, "name", None)
        arguments = getattr(fn, "arguments", None)
        if not name:
            raise ProviderFailure("Groq tool name missing.")
        if isinstance(arguments, str):
            parsed = json.loads(arguments)
        elif isinstance(arguments, dict):
            parsed = arguments
        else:
            raise ProviderFailure("Groq tool arguments are not valid JSON.")
        if operation_hint and name != operation_hint:
            raise ProviderFailure(f"Groq selected unsupported operation {name!r}.")
        if name not in OPERATION_EXECUTORS:
            raise ProviderFailure(f"Groq selected unsupported operation {name!r}.")
        return {"name": name, "arguments": parsed}

    def _parse_tool_call(self, raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        name = raw.get("name")
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValidationError.from_exception_data("ToolArguments", [{"loc": ("arguments",), "msg": "must be a dict", "type": "dict_type"}])
        if name not in OPERATION_EXECUTORS:
            raise UnsupportedQuestionError(f"Unsupported tool operation: {name}")
        allowed_keys = {"max_results"}
        unexpected = set(arguments) - allowed_keys
        if unexpected:
            raise ValueError(f"Unsupported tool arguments: {sorted(unexpected)}")
        max_results = int(arguments.get("max_results", 10))
        if max_results < 1 or max_results > 20:
            raise ValueError("max_results must be between 1 and 20.")
        return name, {"max_results": max_results}

    def _default_answer(self, operation: str, result: dict[str, Any]) -> str:
        if operation == AnalyticsOperation.CATALOG_SUMMARY.value:
            total = result.get("total_products")
            return f"The catalog contains {total} products." if total is not None else "The catalog summary is available."
        if operation == AnalyticsOperation.REVIEW_SUMMARY.value:
            total = result.get("total_review_rows")
            avg = result.get("average_rating")
            if total is not None and avg is not None:
                return f"There are {total} review rows with an average rating of {avg:.4f}."
            return "The overall review summary is available."
        if operation == AnalyticsOperation.REVIEW_RATING_DISTRIBUTION.value:
            buckets = result.get("ratings") or []
            if buckets:
                first = buckets[0]
                return f"The most frequent rating bucket is {first.get('rating')} with {first.get('review_rows')} reviews."
            return "The rating distribution is available."
        if operation == AnalyticsOperation.REVIEW_RECOMMENDATION_SUMMARY.value:
            rate = result.get("recommendation_rate")
            rows = result.get("valid_recommendation_rows")
            if rate is not None and rows is not None:
                return f"The valid recommendation rate is {rate:.4f} across {rows} rows."
            return "The recommendation summary is available."
        if operation == AnalyticsOperation.REVIEW_TRENDS.value:
            trends = result.get("trends") or []
            if trends:
                latest = trends[-1]
                return f"The latest month in the trend data is {latest.get('month')} with {latest.get('review_rows')} reviews."
            return "The monthly trends are available."
        return "The requested deterministic analytics result is available."

    def _grounded_answer(self, operation: str, question: str, result: dict[str, Any]) -> str:
        answer = self._default_answer(operation, result)
        if any(keyword in question.lower() for keyword in ["how many", "count", "total"]):
            key = {
                AnalyticsOperation.CATALOG_SUMMARY.value: "total_products",
                AnalyticsOperation.REVIEW_SUMMARY.value: "total_review_rows",
                AnalyticsOperation.CATALOG_CATEGORY_COUNTS.value: "category_counts",
                AnalyticsOperation.REVIEW_PRODUCTS.value: "products",
            }.get(operation)
            if key and key in result:
                value = result[key]
                if isinstance(value, int):
                    return f"The answer is {value}."
        return answer

    def ask(self, question: str, *, max_results: int = 10) -> AssistantAnalyticsResponse:
        try:
            normalized = _normalize_question(question)
        except UnsupportedQuestionError as exc:
            return AssistantAnalyticsResponse(
                answer="This request is outside the supported deterministic analytics operations.",
                operation=None,
                supported=False,
                result=None,
                filters={"max_results": max_results},
                metric_definition=None,
                source_mart=None,
                provider_status="unsupported_question",
                reason=str(exc),
            )

        operation = _choose_operation(normalized)
        if operation is None:
            return AssistantAnalyticsResponse(
                answer="This request is outside the supported deterministic analytics operations.",
                operation=None,
                supported=False,
                result=None,
                filters={"max_results": max_results},
                metric_definition=None,
                source_mart=None,
                provider_status="unsupported_question",
                reason="Unsupported business or analytical question. Only catalogue and review metrics are available.",
            )

        try:
            result = OPERATION_EXECUTORS[operation](get_database_path(), max_results)
        except Exception as exc:  # pragma: no cover - defensive boundary for DB access issues
            return AssistantAnalyticsResponse(
                answer="The requested deterministic analytics could not be calculated.",
                operation=operation,
                supported=False,
                result=None,
                filters={"max_results": max_results},
                metric_definition=OPERATION_METRIC_DEFINITIONS.get(operation),
                source_mart=SOURCE_MARTS.get(operation),
                provider_status="provider_error",
                reason=str(exc),
            )

        provider_status: Literal["ok", "missing_key", "rate_limit", "timeout", "malformed_response", "provider_error"] = "ok"
        response_text = self._grounded_answer(operation, normalized, result)
        try:
            if not self.is_configured():
                raise MissingGroqAPIKeyError("GROQ_API_KEY is not configured.")
            tool_choice = {"name": operation, "arguments": {"max_results": max_results}}
            provider_call = self._call_provider(prompt=normalized, tools=ANALYTICS_TOOL_DEFINITIONS, operation_hint=operation)
            validated_name, validated_args = self._parse_tool_call(provider_call)
            if validated_name != operation:
                raise ProviderFailure(f"Model selected {validated_name!r} instead of {operation!r}.")
            provider_status = "ok"
            response_text = self._grounded_answer(operation, normalized, result)
        except MissingGroqAPIKeyError as exc:
            provider_status = "missing_key"
            response_text = self._grounded_answer(operation, normalized, result)
            return AssistantAnalyticsResponse(
                answer=response_text,
                operation=operation,
                supported=True,
                result=result,
                filters={"max_results": max_results},
                metric_definition=OPERATION_METRIC_DEFINITIONS.get(operation),
                source_mart=SOURCE_MARTS.get(operation),
                provider_status=provider_status,
                reason=str(exc),
            )
        except Exception as exc:
            provider_status = "provider_error"
            exc_name = type(exc).__name__
            if "RateLimit" in exc_name:
                provider_status = "rate_limit"
            elif isinstance(exc, TimeoutError) or "Timeout" in exc_name:
                provider_status = "timeout"
            elif isinstance(exc, json.JSONDecodeError):
                provider_status = "malformed_response"
            elif isinstance(exc, ValueError) and "Unsupported" in str(exc):
                provider_status = "unsupported_question"
            response_text = self._grounded_answer(operation, normalized, result)
            safe_reason = _sanitize_error_message(str(exc), self.api_key)
            return AssistantAnalyticsResponse(
                answer=response_text,
                operation=operation,
                supported=True,
                result=result,
                filters={"max_results": max_results},
                metric_definition=OPERATION_METRIC_DEFINITIONS.get(operation),
                source_mart=SOURCE_MARTS.get(operation),
                provider_status=provider_status,
                reason=safe_reason,
            )

        return AssistantAnalyticsResponse(
            answer=response_text,
            operation=operation,
            supported=True,
            result=result,
            filters={"max_results": max_results},
            metric_definition=OPERATION_METRIC_DEFINITIONS.get(operation),
            source_mart=SOURCE_MARTS.get(operation),
            provider_status=provider_status,
            reason=None,
        )
