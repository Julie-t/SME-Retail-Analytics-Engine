"""Offline planning and verification helpers for scoped Beauty API extracts."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

PAGE_SIZE = 20
MAX_PAGES = 51
MAX_PRODUCTS_PER_PARTITION = PAGE_SIZE * MAX_PAGES
BATCH_SIZE = 50
MAX_429_RETRIES = 5
PAID_OVERAGE_USD_PER_CALL = 0.02

DOCUMENTED_CATEGORIES = frozenset(
    {
        "skincare",
        "suncare",
        "makeup",
        "haircare",
        "body/bath",
        "fragrance",
        "other",
    }
)
DOCUMENTED_FILTERS = frozenset(
    {
        "category",
        "brand",
        "origin",
        "fragrance_free",
        "alcohol_free",
        "paraben_free",
        "sulfate_free",
        "silicone_free",
        "has_ingredient",
        "excludes_ingredient",
    }
)


class ManifestError(ValueError):
    """Raised when an extraction manifest or mocked API response is invalid."""


@dataclass(frozen=True)
class PartitionSpec:
    partition_id: str
    filters: Mapping[str, Any]
    expected_total: int | None
    expected_pages: int | None
    expected_detail_items: int | None
    status: str
    count_source: str | None
    blocked_reason: str | None


@dataclass(frozen=True)
class CostPolicy:
    plan: str
    remaining_allowance_calls: int | None
    maximum_overage_usd: float | None


@dataclass(frozen=True)
class ExtractionManifest:
    name: str
    selected_categories: tuple[str, ...]
    partitions: tuple[PartitionSpec, ...]
    cost_policy: CostPolicy


@dataclass(frozen=True)
class PartitionCoverage:
    partition_id: str
    reported_total: int | None
    expected_pages: int | None
    fetched_pages: int
    product_ids: tuple[str, ...]
    duplicate_ids: tuple[str, ...]
    complete: bool
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class CoverageReport:
    partitions: tuple[PartitionCoverage, ...]
    unique_product_ids: tuple[str, ...]
    overlap_memberships: Mapping[str, tuple[str, ...]]
    unresolved_gaps: tuple[str, ...]
    covers_declared_partition_union: bool
    covers_selected_categories: bool


@dataclass(frozen=True)
class UsageEstimate:
    listing_requests: int
    detail_batch_requests: int
    retry_reserve_http_requests: int
    worst_case_http_requests: int
    unique_detail_items: int
    billable_calls_without_retries: int
    retry_reserve_billable_calls: int
    worst_case_billable_calls: int
    estimated_overage_usd: float | None
    exceeds_sandbox_hard_cap: bool | None
    within_overage_budget: bool | None


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def expected_page_count(total: int) -> int:
    if not _is_nonnegative_int(total):
        raise ManifestError("Expected result total must be a non-negative integer.")
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


def _validate_uuid(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise ManifestError(f"{field_name} values must be UUID strings.")
    try:
        UUID(value)
    except ValueError as error:
        raise ManifestError(f"{field_name} contains an invalid UUID.") from error


def _parse_partition(
    raw_partition: Any,
    selected_categories: frozenset[str],
) -> PartitionSpec:
    if not isinstance(raw_partition, dict):
        raise ManifestError("Each partition must be a JSON object.")
    required = {
        "id",
        "filters",
        "expected_total",
        "expected_pages",
        "expected_detail_items",
        "status",
        "count_source",
        "blocked_reason",
    }
    if raw_partition.keys() != required:
        missing = sorted(required.difference(raw_partition))
        unexpected = sorted(set(raw_partition).difference(required))
        raise ManifestError(
            f"Partition fields mismatch (missing={missing}, unexpected={unexpected})."
        )

    partition_id = raw_partition["id"]
    if not isinstance(partition_id, str) or not partition_id.strip():
        raise ManifestError("Partition id must be a non-empty string.")

    filters = raw_partition["filters"]
    if not isinstance(filters, dict) or not filters:
        raise ManifestError(f"Partition {partition_id!r} needs at least one filter.")
    unknown_filters = set(filters).difference(DOCUMENTED_FILTERS)
    if unknown_filters:
        raise ManifestError(
            f"Partition {partition_id!r} uses undocumented filters: "
            + ", ".join(sorted(unknown_filters))
        )
    category = filters.get("category")
    if not isinstance(category, str) or category not in selected_categories:
        raise ManifestError(
            f"Partition {partition_id!r} must use a selected documented category."
        )

    for key in ("brand", "origin"):
        if key in filters and (
            not isinstance(filters[key], str) or not filters[key].strip()
        ):
            raise ManifestError(f"Filter {key!r} must be a non-empty string.")
    for key in (
        "fragrance_free",
        "alcohol_free",
        "paraben_free",
        "sulfate_free",
        "silicone_free",
    ):
        if key in filters and not isinstance(filters[key], bool):
            raise ManifestError(f"Filter {key!r} must be boolean.")
    if "has_ingredient" in filters:
        _validate_uuid(filters["has_ingredient"], "has_ingredient")
    if "excludes_ingredient" in filters:
        ingredients = filters["excludes_ingredient"]
        if not isinstance(ingredients, list) or not 1 <= len(ingredients) <= 10:
            raise ManifestError(
                "excludes_ingredient must contain between one and ten UUIDs."
            )
        for ingredient in ingredients:
            _validate_uuid(ingredient, "excludes_ingredient")
        if len(set(ingredients)) != len(ingredients):
            raise ManifestError("excludes_ingredient contains duplicate UUIDs.")

    status = raw_partition["status"]
    if not isinstance(status, str) or status not in {
        "pending_discovery",
        "ready",
        "blocked",
    }:
        raise ManifestError(f"Unsupported status for partition {partition_id!r}.")
    total = raw_partition["expected_total"]
    pages = raw_partition["expected_pages"]
    details = raw_partition["expected_detail_items"]
    count_source = raw_partition["count_source"]
    blocked_reason = raw_partition["blocked_reason"]

    if status == "pending_discovery":
        if any(value is not None for value in (total, pages, details, count_source)):
            raise ManifestError(
                f"Pending partition {partition_id!r} must leave observed counts "
                "and count_source unset."
            )
        if blocked_reason is not None:
            raise ManifestError(
                f"Pending partition {partition_id!r} cannot have a blocked_reason."
            )
    else:
        if not _is_nonnegative_int(total):
            raise ManifestError(
                f"Partition {partition_id!r} needs a non-negative expected_total."
            )
        if not _is_nonnegative_int(pages) or pages != expected_page_count(total):
            raise ManifestError(
                f"Partition {partition_id!r} expected_pages must match its total."
            )
        if not _is_nonnegative_int(details) or details != total:
            raise ManifestError(
                f"Partition {partition_id!r} detail items must equal expected_total."
            )
        if not isinstance(count_source, str) or not count_source.strip():
            raise ManifestError(
                f"Partition {partition_id!r} needs a count_source."
            )
        if status == "ready":
            if total > MAX_PRODUCTS_PER_PARTITION or pages > MAX_PAGES:
                raise ManifestError(
                    f"Partition {partition_id!r} exceeds the documented page limit "
                    "and must be blocked."
                )
            if blocked_reason is not None:
                raise ManifestError(
                    f"Ready partition {partition_id!r} cannot have a blocked_reason."
                )
        elif not isinstance(blocked_reason, str) or not blocked_reason.strip():
            raise ManifestError(
                f"Blocked partition {partition_id!r} needs a blocked_reason."
            )

    return PartitionSpec(
        partition_id=partition_id,
        filters=dict(filters),
        expected_total=total,
        expected_pages=pages,
        expected_detail_items=details,
        status=status,
        count_source=count_source,
        blocked_reason=blocked_reason,
    )


def parse_manifest(payload: Any) -> ExtractionManifest:
    if not isinstance(payload, dict):
        raise ManifestError("Manifest root must be a JSON object.")
    required = {"schema_version", "name", "scope", "cost_policy", "partitions"}
    if payload.keys() != required:
        missing = sorted(required.difference(payload))
        unexpected = sorted(set(payload).difference(required))
        raise ManifestError(
            f"Manifest fields mismatch (missing={missing}, unexpected={unexpected})."
        )
    if payload["schema_version"] != 1:
        raise ManifestError("Only manifest schema_version 1 is supported.")
    name = payload["name"]
    if not isinstance(name, str) or not name.strip():
        raise ManifestError("Manifest name must be a non-empty string.")

    scope = payload["scope"]
    if (
        not isinstance(scope, dict)
        or scope.keys()
        != {"definition", "selected_categories", "includes_uncategorized"}
    ):
        raise ManifestError(
            "scope must define definition, selected_categories, and "
            "includes_uncategorized."
        )
    if scope["definition"] != "union_of_partitions":
        raise ManifestError(
            "Scope definition must be union_of_partitions; category filters alone "
            "do not imply whole-catalogue coverage."
        )
    if scope["includes_uncategorized"] is not False:
        raise ManifestError(
            "The documented filters cannot select uncategorized products; "
            "includes_uncategorized must be false."
        )
    categories = scope["selected_categories"]
    if (
        not isinstance(categories, list)
        or not categories
        or any(
            not isinstance(category, str)
            or category not in DOCUMENTED_CATEGORIES
            for category in categories
        )
        or len(set(categories)) != len(categories)
    ):
        raise ManifestError(
            "selected_categories must be a non-empty, unique list of documented "
            "category values."
        )
    selected_categories = frozenset(categories)

    raw_partitions = payload["partitions"]
    if not isinstance(raw_partitions, list) or not raw_partitions:
        raise ManifestError("Manifest must include at least one partition.")
    partitions = tuple(
        _parse_partition(partition, selected_categories)
        for partition in raw_partitions
    )
    partition_ids = [partition.partition_id for partition in partitions]
    if len(set(partition_ids)) != len(partition_ids):
        raise ManifestError("Partition IDs must be unique.")
    covered_categories = {
        partition.filters["category"] for partition in partitions
    }
    if covered_categories != selected_categories:
        raise ManifestError(
            "Every selected category must appear in at least one partition, and "
            "no unselected category may appear."
        )

    raw_policy = payload["cost_policy"]
    if (
        not isinstance(raw_policy, dict)
        or raw_policy.keys()
        != {
            "plan",
            "remaining_allowance_calls",
            "maximum_overage_usd",
        }
    ):
        raise ManifestError(
            "cost_policy must define plan, remaining_allowance_calls, and "
            "maximum_overage_usd."
        )
    plan = raw_policy["plan"]
    if not isinstance(plan, str) or plan not in {
        "unknown",
        "sandbox",
        "starter",
        "starter_barcode",
        "pro",
        "pro_barcode",
    }:
        raise ManifestError("Unsupported plan value in cost_policy.")
    remaining = raw_policy["remaining_allowance_calls"]
    if remaining is not None and not _is_nonnegative_int(remaining):
        raise ManifestError("remaining_allowance_calls must be a non-negative integer.")
    maximum_overage = raw_policy["maximum_overage_usd"]
    if maximum_overage is not None and (
        isinstance(maximum_overage, bool)
        or not isinstance(maximum_overage, (int, float))
        or not math.isfinite(maximum_overage)
        or maximum_overage < 0
    ):
        raise ManifestError("maximum_overage_usd must be non-negative or null.")

    return ExtractionManifest(
        name=name,
        selected_categories=tuple(categories),
        partitions=partitions,
        cost_policy=CostPolicy(
            plan=plan,
            remaining_allowance_calls=remaining,
            maximum_overage_usd=maximum_overage,
        ),
    )


def load_manifest(path: Path) -> ExtractionManifest:
    try:
        with path.open(encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"Unable to load manifest {path}: {error}") from error
    return parse_manifest(payload)


def _response_int(value: Any, field: str, partition_id: str) -> int:
    if not _is_nonnegative_int(value):
        raise ManifestError(
            f"Partition {partition_id!r} response has invalid {field}."
        )
    return value


def reconcile_listing_pages(
    manifest: ExtractionManifest,
    pages_by_partition: Mapping[str, Sequence[Mapping[str, Any]]],
) -> CoverageReport:
    """Reconcile mocked or separately collected listing pages without networking."""
    specs = {partition.partition_id: partition for partition in manifest.partitions}
    unexpected_partitions = set(pages_by_partition).difference(specs)
    if unexpected_partitions:
        raise ManifestError(
            "Listing results contain unconfigured partitions: "
            + ", ".join(sorted(unexpected_partitions))
        )

    coverage: list[PartitionCoverage] = []
    memberships: dict[str, set[str]] = defaultdict(set)
    unresolved: list[str] = []
    for partition in manifest.partitions:
        pages = pages_by_partition.get(partition.partition_id, ())
        gaps: list[str] = []
        if not pages:
            gaps.append("no listing pages were collected")
            result = PartitionCoverage(
                partition_id=partition.partition_id,
                reported_total=None,
                expected_pages=partition.expected_pages,
                fetched_pages=0,
                product_ids=(),
                duplicate_ids=(),
                complete=False,
                gaps=tuple(gaps),
            )
            coverage.append(result)
            unresolved.extend(
                f"{partition.partition_id}: {gap}" for gap in gaps
            )
            continue

        page_total: int | None = None
        page_ids: list[str] = []
        duplicates: set[str] = set()
        exceeds_limit = False
        for page_index, payload in enumerate(pages, start=1):
            if not isinstance(payload, Mapping):
                raise ManifestError(
                    f"Partition {partition.partition_id!r} page {page_index} "
                    "must be an object."
                )
            results = payload.get("results")
            pagination = payload.get("pagination")
            if not isinstance(results, list) or not isinstance(pagination, Mapping):
                raise ManifestError(
                    f"Partition {partition.partition_id!r} page {page_index} "
                    "must contain results and pagination."
                )
            reported_page = _response_int(
                pagination.get("page"), "pagination.page", partition.partition_id
            )
            total = _response_int(
                pagination.get("total"), "pagination.total", partition.partition_id
            )
            has_more = pagination.get("has_more")
            if not isinstance(has_more, bool):
                raise ManifestError(
                    f"Partition {partition.partition_id!r} has invalid "
                    "pagination.has_more."
                )
            if reported_page != page_index:
                gaps.append(
                    f"page sequence expected {page_index} but API reported "
                    f"{reported_page}"
                )
            if page_total is None:
                page_total = total
                exceeds_limit = total > MAX_PRODUCTS_PER_PARTITION
                if exceeds_limit:
                    gaps.append(
                        f"reported total {total} exceeds the documented "
                        f"{MAX_PRODUCTS_PER_PARTITION}-product partition limit"
                    )
            elif total != page_total:
                gaps.append("pagination.total changed between pages")

            computed_pages = expected_page_count(total)
            expected_result_count = min(
                PAGE_SIZE,
                max(0, total - ((page_index - 1) * PAGE_SIZE)),
            )
            expected_has_more = page_index < computed_pages
            if len(results) != expected_result_count:
                gaps.append(
                    f"page {page_index} returned {len(results)} results; "
                    f"expected {expected_result_count}"
                )
            if has_more != expected_has_more:
                gaps.append(
                    f"page {page_index} has_more={has_more}; "
                    f"expected {expected_has_more}"
                )

            for product in results:
                if not isinstance(product, Mapping):
                    raise ManifestError(
                        f"Partition {partition.partition_id!r} has a non-object "
                        "product listing entry."
                    )
                product_id = product.get("id")
                if not isinstance(product_id, str) or not product_id.strip():
                    raise ManifestError(
                        f"Partition {partition.partition_id!r} has a missing "
                        "product ID."
                    )
                if product_id in page_ids:
                    duplicates.add(product_id)
                page_ids.append(product_id)

        if page_total is not None:
            required_pages = expected_page_count(page_total)
            if len(pages) != required_pages:
                gaps.append(
                    f"collected {len(pages)} of {required_pages} required pages"
                )
            if len(pages) > MAX_PAGES:
                gaps.append("collected pages beyond the documented page limit")
            if partition.expected_total is not None and (
                page_total != partition.expected_total
            ):
                gaps.append(
                    f"reported total {page_total} differs from manifest total "
                    f"{partition.expected_total}"
                )
            if partition.expected_pages is not None and (
                required_pages != partition.expected_pages
            ):
                gaps.append(
                    f"reported page count {required_pages} differs from manifest "
                    f"page count {partition.expected_pages}"
                )
        if duplicates:
            gaps.append(
                "duplicate product IDs within partition: "
                + ", ".join(sorted(duplicates))
            )
        if partition.status == "blocked":
            gaps.append(
                partition.blocked_reason or "partition is marked blocked"
            )
        if exceeds_limit and len(pages) < MAX_PAGES:
            gaps.append(
                "partition is not pageable to completion; do not infer a complete "
                "result from the fetched prefix"
            )

        unique_ids = tuple(dict.fromkeys(page_ids))
        for product_id in unique_ids:
            memberships[product_id].add(partition.partition_id)
        result = PartitionCoverage(
            partition_id=partition.partition_id,
            reported_total=page_total,
            expected_pages=(
                expected_page_count(page_total)
                if page_total is not None
                else partition.expected_pages
            ),
            fetched_pages=len(pages),
            product_ids=unique_ids,
            duplicate_ids=tuple(sorted(duplicates)),
            complete=not gaps,
            gaps=tuple(gaps),
        )
        coverage.append(result)
        unresolved.extend(
            f"{partition.partition_id}: {gap}" for gap in gaps
        )

    exact_category_partitions = {
        partition.filters["category"]: partition.partition_id
        for partition in manifest.partitions
        if set(partition.filters) == {"category"}
    }
    coverage_by_id = {item.partition_id: item for item in coverage}
    covers_selected_categories = all(
        category in exact_category_partitions
        and coverage_by_id[exact_category_partitions[category]].complete
        for category in manifest.selected_categories
    )
    membership_report = {
        product_id: tuple(sorted(partition_ids))
        for product_id, partition_ids in memberships.items()
        if len(partition_ids) > 1
    }
    return CoverageReport(
        partitions=tuple(coverage),
        unique_product_ids=tuple(sorted(memberships)),
        overlap_memberships=membership_report,
        unresolved_gaps=tuple(unresolved),
        covers_declared_partition_union=all(item.complete for item in coverage),
        covers_selected_categories=covers_selected_categories,
    )


def validate_detail_batches(
    expected_product_ids: Sequence[str],
    batch_responses: Sequence[Sequence[Mapping[str, Any] | None]],
) -> tuple[Mapping[str, Any], ...]:
    """Check mocked detail responses against deduplicated IDs before any writes."""
    expected_ids = tuple(expected_product_ids)
    if any(not isinstance(product_id, str) or not product_id for product_id in expected_ids):
        raise ManifestError("Expected detail product IDs must be non-empty strings.")
    if len(set(expected_ids)) != len(expected_ids):
        raise ManifestError("Expected detail product IDs must be deduplicated.")
    expected_batches = math.ceil(len(expected_ids) / BATCH_SIZE)
    if len(batch_responses) != expected_batches:
        raise ManifestError(
            f"Received {len(batch_responses)} detail batches; expected "
            f"{expected_batches}."
        )

    products: list[Mapping[str, Any]] = []
    for batch_index, batch in enumerate(batch_responses):
        start = batch_index * BATCH_SIZE
        requested_ids = expected_ids[start : start + BATCH_SIZE]
        if len(batch) != len(requested_ids):
            raise ManifestError(
                f"Detail batch {batch_index + 1} is incomplete."
            )
        received_ids: list[str] = []
        for record in batch:
            if not isinstance(record, Mapping):
                raise ManifestError(
                    f"Detail batch {batch_index + 1} contains a null or invalid record."
                )
            product_id = record.get("id")
            if not isinstance(product_id, str) or not product_id:
                raise ManifestError(
                    f"Detail batch {batch_index + 1} contains a missing product ID."
                )
            received_ids.append(product_id)
            products.append(record)
        if received_ids != list(requested_ids):
            raise ManifestError(
                f"Detail batch {batch_index + 1} IDs or order do not match the "
                "requested manifest IDs."
            )
    return tuple(products)


def estimate_usage(
    manifest: ExtractionManifest,
    coverage: CoverageReport,
    *,
    remaining_allowance_calls: int | None = None,
    maximum_overage_usd: float | None = None,
    retry_attempts: int = MAX_429_RETRIES,
) -> UsageEstimate:
    """Estimate list and item-metered detail usage after listing, before details."""
    configured_partitions = {
        partition.partition_id: partition for partition in manifest.partitions
    }
    coverage_by_id = {
        partition.partition_id: partition for partition in coverage.partitions
    }
    if (
        len(coverage_by_id) != len(coverage.partitions)
        or coverage_by_id.keys() != configured_partitions.keys()
    ):
        raise ManifestError(
            "Coverage report must contain exactly one result for every manifest "
            "partition."
        )
    if not coverage.covers_declared_partition_union:
        raise ManifestError(
            "Cannot authorize detail requests while listing coverage has gaps."
        )
    if coverage.unresolved_gaps:
        raise ManifestError(
            "Cannot authorize detail requests while unresolved listing gaps remain."
        )
    for partition_id, result in coverage_by_id.items():
        spec = configured_partitions[partition_id]
        if spec.status != "ready":
            raise ManifestError(
                "Cannot authorize detail requests until every manifest partition "
                "has a recorded ready status."
            )
        if (
            not result.complete
            or result.gaps
            or result.duplicate_ids
            or result.reported_total != spec.expected_total
            or result.expected_pages != spec.expected_pages
            or result.fetched_pages != spec.expected_pages
            or len(result.product_ids) != spec.expected_total
            or len(set(result.product_ids)) != len(result.product_ids)
            or any(
                not isinstance(product_id, str) or not product_id
                for product_id in result.product_ids
            )
        ):
            raise ManifestError(
                f"Coverage report for partition {partition_id!r} does not match "
                "its validated manifest counts."
            )
    report_union = tuple(
        sorted(
            {
                product_id
                for result in coverage.partitions
                for product_id in result.product_ids
            }
        )
    )
    if report_union != coverage.unique_product_ids:
        raise ManifestError(
            "Coverage report's deduplicated ID union does not match its partitions."
        )
    if not _is_nonnegative_int(retry_attempts):
        raise ManifestError("retry_attempts must be a non-negative integer.")
    if remaining_allowance_calls is None:
        remaining_allowance_calls = (
            manifest.cost_policy.remaining_allowance_calls
        )
    if remaining_allowance_calls is not None and not _is_nonnegative_int(
        remaining_allowance_calls
    ):
        raise ManifestError("remaining_allowance_calls must be non-negative or null.")
    if maximum_overage_usd is None:
        maximum_overage_usd = manifest.cost_policy.maximum_overage_usd
    if maximum_overage_usd is not None and (
        isinstance(maximum_overage_usd, bool)
        or not isinstance(maximum_overage_usd, (int, float))
        or not math.isfinite(maximum_overage_usd)
        or maximum_overage_usd < 0
    ):
        raise ManifestError("maximum_overage_usd must be non-negative or null.")

    listing_requests = sum(partition.fetched_pages for partition in coverage.partitions)
    detail_items = len(coverage.unique_product_ids)
    detail_batches = (detail_items + BATCH_SIZE - 1) // BATCH_SIZE
    http_requests = listing_requests + detail_batches
    retry_reserve_requests = http_requests * retry_attempts
    base_calls = listing_requests + detail_items
    retry_reserve = base_calls * retry_attempts
    worst_case_calls = base_calls + retry_reserve

    estimated_overage = None
    hard_cap_exceeded = None
    within_budget = None
    if remaining_allowance_calls is not None:
        excess_calls = max(0, worst_case_calls - remaining_allowance_calls)
        if manifest.cost_policy.plan in {"starter", "starter_barcode", "pro", "pro_barcode"}:
            estimated_overage = round(
                excess_calls * PAID_OVERAGE_USD_PER_CALL,
                2,
            )
            if maximum_overage_usd is not None:
                within_budget = estimated_overage <= maximum_overage_usd
        elif manifest.cost_policy.plan == "sandbox":
            hard_cap_exceeded = excess_calls > 0

    return UsageEstimate(
        listing_requests=listing_requests,
        detail_batch_requests=detail_batches,
        retry_reserve_http_requests=retry_reserve_requests,
        worst_case_http_requests=http_requests + retry_reserve_requests,
        unique_detail_items=detail_items,
        billable_calls_without_retries=base_calls,
        retry_reserve_billable_calls=retry_reserve,
        worst_case_billable_calls=worst_case_calls,
        estimated_overage_usd=estimated_overage,
        exceeds_sandbox_hard_cap=hard_cap_exceeded,
        within_overage_budget=within_budget,
    )


def authorize_detail_usage(
    manifest: ExtractionManifest,
    coverage: CoverageReport,
    *,
    remaining_allowance_calls: int | None = None,
    maximum_overage_usd: float | None = None,
    retry_attempts: int = MAX_429_RETRIES,
) -> UsageEstimate:
    """Fail closed unless verified allowance and approved spend cover worst case."""
    plan = manifest.cost_policy.plan
    if plan == "unknown":
        raise ManifestError("Cannot authorize details with an unknown API plan.")

    allowance = (
        remaining_allowance_calls
        if remaining_allowance_calls is not None
        else manifest.cost_policy.remaining_allowance_calls
    )
    if allowance is None:
        raise ManifestError(
            "Cannot authorize details without a verified remaining allowance."
        )

    overage_limit = (
        maximum_overage_usd
        if maximum_overage_usd is not None
        else manifest.cost_policy.maximum_overage_usd
    )
    if overage_limit is None:
        raise ManifestError(
            "Cannot authorize details without an operator-approved maximum "
            "overage."
        )

    estimate = estimate_usage(
        manifest,
        coverage,
        remaining_allowance_calls=allowance,
        maximum_overage_usd=overage_limit,
        retry_attempts=retry_attempts,
    )
    if plan == "sandbox":
        if estimate.exceeds_sandbox_hard_cap is not False:
            raise ManifestError(
                "Cannot authorize details because the Sandbox hard cap would "
                "be exceeded."
            )
    elif estimate.within_overage_budget is not True:
        raise ManifestError(
            "Cannot authorize details because the retry-aware estimated "
            f"overage ({estimate.estimated_overage_usd}) exceeds the approved "
            f"maximum ({overage_limit:.2f})."
        )
    return estimate
