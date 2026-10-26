from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.ingestion.beauty_extraction_manifest import (
    MAX_PRODUCTS_PER_PARTITION,
    ManifestError,
    authorize_detail_usage,
    estimate_usage,
    load_manifest,
    parse_manifest,
    reconcile_listing_pages,
    validate_detail_batches,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_MANIFEST = (
    PROJECT_ROOT / "config" / "beauty_extraction_manifest.example.json"
)
PROPOSED_MANIFEST = (
    PROJECT_ROOT / "config" / "beauty_extraction_manifest.proposed.json"
)


def pending_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": "test-skincare-subset",
        "scope": {
            "definition": "union_of_partitions",
            "selected_categories": ["skincare"],
            "includes_uncategorized": False,
        },
        "cost_policy": {
            "plan": "starter",
            "remaining_allowance_calls": 5,
            "maximum_overage_usd": 0.06,
        },
        "partitions": [
            {
                "id": "category-skincare",
                "filters": {"category": "skincare"},
                "expected_total": None,
                "expected_pages": None,
                "expected_detail_items": None,
                "status": "pending_discovery",
                "count_source": None,
                "blocked_reason": None,
            }
        ],
    }


def set_ready(
    manifest: dict[str, Any],
    partition_id: str,
    filters: dict[str, Any],
    total: int,
    *,
    status: str = "ready",
) -> None:
    import math

    manifest["partitions"].append(
        {
            "id": partition_id,
            "filters": filters,
            "expected_total": total,
            "expected_pages": max(1, math.ceil(total / 20)),
            "expected_detail_items": total,
            "status": status,
            "count_source": "offline test fixture only",
            "blocked_reason": (
                "test partition deliberately blocked" if status == "blocked" else None
            ),
        }
    )


def listing_page(
    page: int,
    total: int,
    ids: list[str],
    has_more: bool,
) -> dict[str, Any]:
    return {
        "results": [{"id": product_id} for product_id in ids],
        "pagination": {
            "page": page,
            "has_more": has_more,
            "total": total,
        },
    }


def ready_overlap_manifest():
    payload = pending_manifest()
    payload["partitions"][0].update(
        {
            "expected_total": 2,
            "expected_pages": 1,
            "expected_detail_items": 2,
            "status": "ready",
            "count_source": "offline test fixture only",
        }
    )
    set_ready(
        payload,
        "fragrance-free-skincare",
        {"category": "skincare", "fragrance_free": True},
        1,
    )
    return parse_manifest(payload)


def test_example_manifest_is_valid_but_not_ready_for_execution() -> None:
    manifest = load_manifest(EXAMPLE_MANIFEST)

    assert manifest.selected_categories == ("skincare",)
    assert len(manifest.partitions) == 1
    assert manifest.partitions[0].status == "pending_discovery"
    assert manifest.partitions[0].expected_total is None
    assert manifest.cost_policy.remaining_allowance_calls is None


def test_proposed_manifest_is_explicit_and_pending_discovery() -> None:
    manifest = load_manifest(PROPOSED_MANIFEST)

    assert manifest.name == "proposed-skincare-fragrance-free-subset"
    assert manifest.selected_categories == ("skincare",)
    assert len(manifest.partitions) == 1
    partition = manifest.partitions[0]
    assert partition.filters == {
        "category": "skincare",
        "fragrance_free": True,
    }
    assert partition.status == "pending_discovery"
    assert partition.expected_total is None
    assert partition.expected_pages is None
    assert partition.expected_detail_items is None
    assert manifest.cost_policy.plan == "unknown"
    assert manifest.cost_policy.remaining_allowance_calls is None
    assert manifest.cost_policy.maximum_overage_usd is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: data["scope"].update({"selected_categories": []}),
            "selected_categories",
        ),
        (
            lambda data: data["partitions"][0]["filters"].update({"page_size": 20}),
            "undocumented filters",
        ),
        (
            lambda data: data["partitions"][0].update(
                {
                    "expected_total": 1021,
                    "expected_pages": 52,
                    "expected_detail_items": 1021,
                    "status": "ready",
                    "count_source": "fixture",
                }
            ),
            "must be blocked",
        ),
        (
            lambda data: data["scope"].update({"includes_uncategorized": True}),
            "cannot select uncategorized",
        ),
    ],
)
def test_manifest_rejects_unsafe_or_undocumented_values(
    mutate: Any,
    message: str,
) -> None:
    payload = pending_manifest()
    mutate(payload)

    with pytest.raises(ManifestError, match=message):
        parse_manifest(payload)


def test_manifest_rejects_counts_when_partition_is_pending() -> None:
    payload = pending_manifest()
    payload["partitions"][0]["expected_total"] = 4

    with pytest.raises(ManifestError, match="leave observed counts"):
        parse_manifest(payload)


def test_manifest_rejects_a_selected_category_without_a_partition() -> None:
    payload = pending_manifest()
    payload["scope"]["selected_categories"] = ["skincare", "makeup"]

    with pytest.raises(ManifestError, match="Every selected category"):
        parse_manifest(payload)


def test_manifest_rejects_unproven_full_catalogue_scope_claim() -> None:
    payload = pending_manifest()
    payload["scope"]["definition"] = "full_catalogue"

    with pytest.raises(ManifestError, match="union_of_partitions"):
        parse_manifest(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("expected_pages", 1, "expected_pages must match"),
        ("expected_detail_items", 20, "detail items must equal expected_total"),
    ],
)
def test_manifest_rejects_inconsistent_partition_totals(
    field: str,
    value: int,
    message: str,
) -> None:
    payload = pending_manifest()
    payload["partitions"][0].update(
        {
            "expected_total": 21,
            "expected_pages": 2,
            "expected_detail_items": 21,
            "status": "ready",
            "count_source": "offline test fixture only",
        }
    )
    payload["partitions"][0][field] = value

    with pytest.raises(ManifestError, match=message):
        parse_manifest(payload)


def test_reconciliation_deduplicates_overlapping_ids_and_preserves_membership() -> None:
    manifest = ready_overlap_manifest()

    report = reconcile_listing_pages(
        manifest,
        {
            "category-skincare": [
                listing_page(1, 2, ["p1", "p2"], False)
            ],
            "fragrance-free-skincare": [
                listing_page(1, 1, ["p2"], False)
            ],
        },
    )

    assert report.covers_declared_partition_union
    assert report.covers_selected_categories
    assert report.unique_product_ids == ("p1", "p2")
    assert report.overlap_memberships == {
        "p2": ("category-skincare", "fragrance-free-skincare")
    }
    assert report.unresolved_gaps == ()


def test_filtered_partition_does_not_claim_selected_category_completeness() -> None:
    manifest = load_manifest(PROPOSED_MANIFEST)
    report = reconcile_listing_pages(
        manifest,
        {
            "skincare-fragrance-free": [
                listing_page(1, 1, ["fixture-id"], False)
            ]
        },
    )

    assert report.covers_declared_partition_union
    assert not report.covers_selected_categories


def test_missing_partition_pages_are_reported_as_unresolved_coverage() -> None:
    manifest = ready_overlap_manifest()
    report = reconcile_listing_pages(
        manifest,
        {"category-skincare": [listing_page(1, 2, ["p1", "p2"], False)]},
    )

    assert not report.covers_declared_partition_union
    assert report.covers_selected_categories
    assert any(
        "fragrance-free-skincare: no listing pages were collected" in gap
        for gap in report.unresolved_gaps
    )
    with pytest.raises(ManifestError, match="listing coverage has gaps"):
        estimate_usage(manifest, report)


def test_pending_manifest_cannot_authorize_details_even_after_mocked_discovery() -> None:
    manifest = parse_manifest(pending_manifest())
    report = reconcile_listing_pages(
        manifest,
        {"category-skincare": [listing_page(1, 2, ["p1", "p2"], False)]},
    )

    assert report.covers_declared_partition_union
    with pytest.raises(ManifestError, match="recorded ready status"):
        estimate_usage(manifest, report)


def test_incomplete_pagination_does_not_allow_detail_cost_authorization() -> None:
    payload = pending_manifest()
    payload["partitions"][0].update(
        {
            "expected_total": 21,
            "expected_pages": 2,
            "expected_detail_items": 21,
            "status": "ready",
            "count_source": "offline test fixture only",
        }
    )
    manifest = parse_manifest(payload)
    pages = [
        listing_page(1, 21, [f"p{index}" for index in range(20)], True)
    ]

    report = reconcile_listing_pages(manifest, {"category-skincare": pages})

    assert not report.covers_declared_partition_union
    assert any("collected 1 of 2 required pages" in gap for gap in report.unresolved_gaps)
    with pytest.raises(ManifestError, match="listing coverage has gaps"):
        estimate_usage(manifest, report)


def test_duplicate_ids_inside_one_partition_are_a_gap_not_deduplicated_away() -> None:
    manifest = ready_overlap_manifest()
    report = reconcile_listing_pages(
        manifest,
        {
            "category-skincare": [
                listing_page(1, 2, ["p1", "p1"], False)
            ],
            "fragrance-free-skincare": [
                listing_page(1, 1, ["p2"], False)
            ],
        },
    )

    assert not report.covers_declared_partition_union
    assert any("duplicate product IDs within partition" in gap for gap in report.unresolved_gaps)
    assert "p1" in report.unique_product_ids
    with pytest.raises(ManifestError):
        estimate_usage(manifest, report)


def test_partition_above_documented_page_capacity_is_blocked_and_unresolved() -> None:
    payload = pending_manifest()
    set_ready(
        payload,
        "blocked-skincare",
        {"category": "skincare", "origin": "USA"},
        MAX_PRODUCTS_PER_PARTITION + 1,
        status="blocked",
    )
    payload["partitions"][0]["status"] = "blocked"
    payload["partitions"][0]["expected_total"] = 2
    payload["partitions"][0]["expected_pages"] = 1
    payload["partitions"][0]["expected_detail_items"] = 2
    payload["partitions"][0]["count_source"] = "offline test fixture only"
    payload["partitions"][0]["blocked_reason"] = "test baseline is blocked"
    manifest = parse_manifest(payload)

    response_ids = [f"p{index}" for index in range(20)]
    report = reconcile_listing_pages(
        manifest,
        {
            "category-skincare": [
                listing_page(1, 2, ["a", "b"], False)
            ],
            "blocked-skincare": [
                listing_page(1, MAX_PRODUCTS_PER_PARTITION + 1, response_ids, True)
            ],
        },
    )

    assert not report.covers_declared_partition_union
    assert any("exceeds the documented 1020-product" in gap for gap in report.unresolved_gaps)
    assert any("deliberately blocked" in gap for gap in report.unresolved_gaps)


def test_listing_total_change_and_page_manifest_mismatch_are_gaps() -> None:
    payload = pending_manifest()
    payload["partitions"][0].update(
        {
            "expected_total": 21,
            "expected_pages": 2,
            "expected_detail_items": 21,
            "status": "ready",
            "count_source": "offline test fixture only",
        }
    )
    manifest = parse_manifest(payload)
    first = listing_page(1, 21, [f"p{index}" for index in range(20)], True)
    second = listing_page(2, 22, ["p20"], False)

    report = reconcile_listing_pages(
        manifest,
        {"category-skincare": [first, second]},
    )

    assert not report.covers_declared_partition_union
    assert any("pagination.total changed" in gap for gap in report.unresolved_gaps)
    assert any("returned 1 results; expected 2" in gap for gap in report.unresolved_gaps)


def test_detail_batches_reject_null_missing_duplicate_and_unordered_ids() -> None:
    with pytest.raises(ManifestError, match="null or invalid"):
        validate_detail_batches(["p1"], [[None]])
    with pytest.raises(ManifestError, match="IDs or order"):
        validate_detail_batches(["p1", "p2"], [[{"id": "p2"}, {"id": "p1"}]])
    with pytest.raises(ManifestError, match="missing product ID"):
        validate_detail_batches(["p1"], [[{"name": "no id"}]])


def test_detail_batches_accept_complete_response_for_deduplicated_union() -> None:
    result = validate_detail_batches(
        ["p1", "p2"],
        [[{"id": "p1"}, {"id": "p2"}]],
    )

    assert [item["id"] for item in result] == ["p1", "p2"]


def test_cost_estimate_deduplicates_items_and_reserves_retry_cost() -> None:
    manifest = ready_overlap_manifest()
    report = reconcile_listing_pages(
        manifest,
        {
            "category-skincare": [
                listing_page(1, 2, ["p1", "p2"], False)
            ],
            "fragrance-free-skincare": [
                listing_page(1, 1, ["p2"], False)
            ],
        },
    )

    estimate = estimate_usage(manifest, report, retry_attempts=1)

    assert estimate.listing_requests == 2
    assert estimate.unique_detail_items == 2
    assert estimate.detail_batch_requests == 1
    assert estimate.retry_reserve_http_requests == 3
    assert estimate.worst_case_http_requests == 6
    assert estimate.billable_calls_without_retries == 4
    assert estimate.retry_reserve_billable_calls == 4
    assert estimate.worst_case_billable_calls == 8
    assert estimate.estimated_overage_usd == 0.06
    assert estimate.within_overage_budget is True


def test_cost_estimate_rejects_coverage_not_matching_manifest_partitions() -> None:
    manifest = ready_overlap_manifest()
    report = reconcile_listing_pages(
        manifest,
        {
            "category-skincare": [
                listing_page(1, 2, ["p1", "p2"], False)
            ],
            "fragrance-free-skincare": [
                listing_page(1, 1, ["p2"], False)
            ],
        },
    )
    forged_report = replace(report, partitions=report.partitions[:1])

    with pytest.raises(ManifestError, match="exactly one result"):
        estimate_usage(manifest, forged_report)
    report_with_unresolved_gaps = replace(
        report,
        unresolved_gaps=("unresolved gap retained in report",),
    )
    with pytest.raises(ManifestError, match="unresolved listing gaps"):
        estimate_usage(manifest, report_with_unresolved_gaps)


def test_detail_authorization_requires_verified_plan_allowance_and_maximum() -> None:
    manifest = ready_overlap_manifest()
    report = reconcile_listing_pages(
        manifest,
        {
            "category-skincare": [
                listing_page(1, 2, ["p1", "p2"], False)
            ],
            "fragrance-free-skincare": [
                listing_page(1, 1, ["p2"], False)
            ],
        },
    )
    unknown_plan = replace(
        manifest,
        cost_policy=replace(manifest.cost_policy, plan="unknown"),
    )
    unknown_allowance = replace(
        manifest,
        cost_policy=replace(
            manifest.cost_policy,
            remaining_allowance_calls=None,
        ),
    )
    unknown_maximum = replace(
        manifest,
        cost_policy=replace(
            manifest.cost_policy,
            maximum_overage_usd=None,
        ),
    )

    with pytest.raises(ManifestError, match="unknown API plan"):
        authorize_detail_usage(unknown_plan, report, retry_attempts=1)
    with pytest.raises(ManifestError, match="verified remaining allowance"):
        authorize_detail_usage(unknown_allowance, report, retry_attempts=1)
    with pytest.raises(ManifestError, match="operator-approved maximum"):
        authorize_detail_usage(unknown_maximum, report, retry_attempts=1)


def test_detail_authorization_rejects_retry_aware_cost_above_approved_limit() -> None:
    manifest = ready_overlap_manifest()
    report = reconcile_listing_pages(
        manifest,
        {
            "category-skincare": [
                listing_page(1, 2, ["p1", "p2"], False)
            ],
            "fragrance-free-skincare": [
                listing_page(1, 1, ["p2"], False)
            ],
        },
    )

    with pytest.raises(ManifestError, match="exceeds the approved maximum"):
        authorize_detail_usage(
            manifest,
            report,
            maximum_overage_usd=0.04,
            retry_attempts=1,
        )


def test_detail_authorization_accepts_verified_estimate_within_limit() -> None:
    manifest = ready_overlap_manifest()
    report = reconcile_listing_pages(
        manifest,
        {
            "category-skincare": [
                listing_page(1, 2, ["p1", "p2"], False)
            ],
            "fragrance-free-skincare": [
                listing_page(1, 1, ["p2"], False)
            ],
        },
    )

    estimate = authorize_detail_usage(manifest, report, retry_attempts=1)

    assert estimate.estimated_overage_usd == 0.06
    assert estimate.within_overage_budget is True


def test_detail_authorization_rejects_sandbox_hard_cap_overrun() -> None:
    manifest = ready_overlap_manifest()
    manifest = replace(
        manifest,
        cost_policy=replace(
            manifest.cost_policy,
            plan="sandbox",
            remaining_allowance_calls=2,
            maximum_overage_usd=0.0,
        ),
    )
    report = reconcile_listing_pages(
        manifest,
        {
            "category-skincare": [
                listing_page(1, 2, ["p1", "p2"], False)
            ],
            "fragrance-free-skincare": [
                listing_page(1, 1, ["p2"], False)
            ],
        },
    )

    with pytest.raises(ManifestError, match="Sandbox hard cap"):
        authorize_detail_usage(manifest, report, retry_attempts=0)


def test_sandbox_hard_cap_overrun_is_not_reported_as_paid_overage() -> None:
    payload = pending_manifest()
    payload["cost_policy"].update(
        {
            "plan": "sandbox",
            "remaining_allowance_calls": 3,
        }
    )
    payload["partitions"][0].update(
        {
            "expected_total": 2,
            "expected_pages": 1,
            "expected_detail_items": 2,
            "status": "ready",
            "count_source": "offline test fixture only",
        }
    )
    manifest = parse_manifest(payload)
    report = reconcile_listing_pages(
        manifest,
        {"category-skincare": [listing_page(1, 2, ["p1", "p2"], False)]},
    )

    estimate = estimate_usage(manifest, report, retry_attempts=0)

    assert estimate.worst_case_billable_calls == 3
    assert estimate.estimated_overage_usd is None
    assert estimate.exceeds_sandbox_hard_cap is False


def test_unknown_remaining_allowance_keeps_paid_overage_unknown() -> None:
    payload = pending_manifest()
    payload["partitions"][0].update(
        {
            "expected_total": 2,
            "expected_pages": 1,
            "expected_detail_items": 2,
            "status": "ready",
            "count_source": "offline test fixture only",
        }
    )
    payload["cost_policy"]["remaining_allowance_calls"] = None
    manifest = parse_manifest(payload)
    report = reconcile_listing_pages(
        manifest,
        {"category-skincare": [listing_page(1, 2, ["p1", "p2"], False)]},
    )

    estimate = estimate_usage(manifest, report, retry_attempts=0)

    assert estimate.estimated_overage_usd is None
    assert estimate.within_overage_budget is None


def test_example_manifest_counts_are_pending_not_fabricated() -> None:
    payload = json.loads(EXAMPLE_MANIFEST.read_text(encoding="utf-8"))

    assert payload["partitions"][0]["expected_total"] is None
    assert payload["partitions"][0]["expected_pages"] is None
    assert payload["partitions"][0]["expected_detail_items"] is None
    assert payload["partitions"][0]["count_source"] is None
