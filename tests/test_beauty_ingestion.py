from __future__ import annotations

import json
from typing import Any

import duckdb
import pytest
import requests

from src.ingestion import load_beauty_api_to_duckdb as ingestion
from src.ingestion.load_beauty_api_to_duckdb import (
    MAX_429_RETRIES,
    MAX_PAGES,
    _fetch_full_products,
    _fetch_slim_products,
)


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(
        self,
        method: str,
        url: str,
        timeout: int,
        **kwargs: Any,
    ) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def listing_page(
    page: int,
    total: int,
    products: list[dict[str, str]],
    has_more: bool,
) -> FakeResponse:
    return FakeResponse(
        {
            "results": products,
            "pagination": {
                "page": page,
                "has_more": has_more,
                "total": total,
            },
        }
    )


def full_product(product_id: str = "p1") -> dict[str, Any]:
    return {
        "id": product_id,
        "brand": "Example",
        "name": "Product",
        "image_url": None,
        "category": None,
        "origin": None,
        "contains_fragrance": False,
        "contains_drying_alcohol": False,
        "contains_parabens": False,
        "contains_sulfates": False,
        "contains_silicones": False,
        "ingredients": [{"position": 0, "name": "Water"}],
    }


def prepared_product_frame(product_id: str = "p1"):
    product = full_product(product_id)
    product["ingredients"] = json.dumps(product["ingredients"])
    return ingestion._products_frame([product])


def test_legacy_loader_requires_explicit_opt_in() -> None:
    with pytest.raises(SystemExit) as error:
        ingestion.main([])

    assert error.value.code == 2


def test_legacy_loader_opt_in_still_requires_api_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("BEAUTY_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Set BEAUTY_API_KEY"):
        ingestion.main(["--allow-legacy-beauty-api"])


def replace_test_frame_with_sql(
    connection: duckdb.DuckDBPyConnection,
    frame: Any,
    table_name: str,
    view_name: str,
) -> None:
    del view_name
    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    values = ", ".join(
        "("
        + ", ".join(
            literal(str(row[field]))
            for field in ("id", "brand", "name", "ingredients")
        )
        + ")"
        for row in frame.iter_rows(named=True)
    )
    connection.execute(
        f"CREATE OR REPLACE TABLE raw.{table_name} AS "
        f"SELECT * FROM (VALUES {values}) AS products "
        "(id, brand, name, ingredients)"
    )


def test_fetch_slim_products_fails_fast_above_documented_page_capacity() -> None:
    session = FakeSession(
        [listing_page(1, MAX_PAGES * 20 + 1, [{"id": "p1"}], True)]
    )

    with pytest.raises(RuntimeError, match="documented page limit"):
        _fetch_slim_products(session)  # type: ignore[arg-type]

    assert len(session.calls) == 1


def test_fetch_slim_products_validates_manifest_and_returns_all_unique_ids() -> None:
    first_page = [{"id": f"p{index}"} for index in range(1, 21)]
    session = FakeSession(
        [
            listing_page(1, 21, first_page, True),
            listing_page(2, 21, [{"id": "p21"}], False),
        ]
    )

    products = _fetch_slim_products(session)  # type: ignore[arg-type]

    assert [product["id"] for product in products] == [
        *(f"p{index}" for index in range(1, 22))
    ]
    assert len(session.calls) == 2


def test_requests_are_paced_at_the_documented_sandbox_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    sleeps: list[float] = []

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(ingestion.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ingestion.time, "sleep", sleep)
    session = FakeSession(
        [
            listing_page(
                1,
                21,
                [{"id": f"p{index}"} for index in range(1, 21)],
                True,
            ),
            listing_page(2, 21, [{"id": "p21"}], False),
        ]
    )

    _fetch_slim_products(session)  # type: ignore[arg-type]

    assert sleeps == [ingestion.MIN_REQUEST_INTERVAL_SECONDS]


def test_fetch_slim_products_rejects_duplicate_ids_across_pages() -> None:
    first_page = [{"id": f"p{index}"} for index in range(1, 21)]
    session = FakeSession(
        [
            listing_page(1, 21, first_page, True),
            listing_page(2, 21, [{"id": "p20"}], False),
        ]
    )

    with pytest.raises(ValueError, match="Duplicate product ID"):
        _fetch_slim_products(session)  # type: ignore[arg-type]


def test_fetch_slim_products_rejects_inconsistent_pagination_metadata() -> None:
    session = FakeSession(
        [listing_page(1, 2, [{"id": "p1"}], False)]
    )

    with pytest.raises(RuntimeError, match="pagination manifest"):
        _fetch_slim_products(session)  # type: ignore[arg-type]


def test_rate_limit_retries_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion.time, "sleep", lambda _: None)
    session = FakeSession(
        [
            *[
                FakeResponse({}, status_code=429)
                for _ in range(MAX_429_RETRIES)
            ],
            FakeResponse(
                {
                    "results": [{"id": "p1"}],
                    "pagination": {"page": 1, "has_more": False, "total": 1},
                }
            ),
        ]
    )

    assert _fetch_slim_products(session) == [{"id": "p1"}]  # type: ignore[arg-type]
    assert len(session.calls) == MAX_429_RETRIES + 1


def test_rate_limit_retry_exhaustion_surfaces_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion.time, "sleep", lambda _: None)
    session = FakeSession(
        [
            FakeResponse({}, status_code=429)
            for _ in range(MAX_429_RETRIES + 1)
        ]
    )

    with pytest.raises(requests.HTTPError, match="429"):
        _fetch_slim_products(session)  # type: ignore[arg-type]

    assert len(session.calls) == MAX_429_RETRIES + 1


def test_fetch_full_products_preserves_nested_ingredients_as_json() -> None:
    session = FakeSession(
        [FakeResponse([full_product()])]
    )

    products = _fetch_full_products(
        session,  # type: ignore[arg-type]
        [{"id": "p1"}],
    )

    assert products[0]["id"] == "p1"
    assert products[0]["ingredients"] == '[{"position": 0, "name": "Water"}]'


@pytest.mark.parametrize(
    "payload",
    [
        [None],
        [{"id": "unexpected"}],
        [{"id": "p1"}, {"id": "p1"}],
    ],
)
def test_fetch_full_products_rejects_incomplete_or_invalid_batches(
    payload: list[Any],
) -> None:
    session = FakeSession([FakeResponse(payload)])

    with pytest.raises(ValueError):
        _fetch_full_products(
            session,  # type: ignore[arg-type]
            [{"id": "p1"}, {"id": "p2"}]
            if len(payload) == 2
            else [{"id": "p1"}],
        )


def test_fetch_full_products_accepts_an_empty_catalog_without_requests() -> None:
    session = FakeSession([])

    assert _fetch_full_products(session, []) == []  # type: ignore[arg-type]
    assert session.calls == []


@pytest.mark.parametrize(
    "update",
    [
        {"ingredients": None},
        {"ingredients": [{"position": 0}]},
        {"ingredients": [{"position": "0", "name": "Water"}]},
        {"contains_fragrance": None},
    ],
)
def test_fetch_full_products_rejects_invalid_documented_payload_fields(
    update: dict[str, Any],
) -> None:
    product = full_product()
    product.update(update)
    session = FakeSession([FakeResponse([product])])

    with pytest.raises(ValueError):
        _fetch_full_products(
            session,  # type: ignore[arg-type]
            [{"id": "p1"}],
        )


def test_fetch_full_products_rejects_response_order_mismatch() -> None:
    session = FakeSession(
        [FakeResponse([full_product("p2"), full_product("p1")])]
    )

    with pytest.raises(ValueError, match="order"):
        _fetch_full_products(
            session,  # type: ignore[arg-type]
            [{"id": "p1"}, {"id": "p2"}],
        )


def test_raw_product_replacement_rolls_back_on_post_write_failure(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "catalog.duckdb"
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("CREATE SCHEMA raw")
        connection.execute(
            "CREATE TABLE raw.raw_products "
            "(id VARCHAR, brand VARCHAR, name VARCHAR, ingredients VARCHAR)"
        )
        connection.execute(
            "INSERT INTO raw.raw_products VALUES "
            "('old-id', 'Old brand', 'Old product', '[]')"
        )

        def fail_verification(*_: Any) -> None:
            raise RuntimeError("verification failed")

        monkeypatch.setattr(ingestion, "_write_frame", replace_test_frame_with_sql)
        monkeypatch.setattr(ingestion, "_verify_raw_products", fail_verification)

        with pytest.raises(RuntimeError, match="verification failed"):
            ingestion._replace_raw_products(
                connection,
                prepared_product_frame(),
                1,
            )

        assert connection.execute(
            "SELECT id FROM raw.raw_products"
        ).fetchall() == [("old-id",)]
    finally:
        connection.close()


def test_raw_product_replacement_commits_verified_catalog(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(str(tmp_path / "catalog.duckdb"))
    try:
        monkeypatch.setattr(ingestion, "_write_frame", replace_test_frame_with_sql)
        ingestion._replace_raw_products(
            connection,
            prepared_product_frame(),
            1,
        )
        assert connection.execute(
            "SELECT id, ingredients FROM raw.raw_products"
        ).fetchall() == [("p1", '[{"position": 0, "name": "Water"}]')]
    finally:
        connection.close()


def test_create_verified_backup_is_an_exact_readable_copy(tmp_path: Any) -> None:
    database_path = tmp_path / "catalog.duckdb"
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("CREATE TABLE catalog AS SELECT 1 AS product_count")
        connection.execute("CREATE SCHEMA raw")
        connection.execute(
            "CREATE TABLE raw.raw_products AS "
            "SELECT 'p1' AS id, '[]' AS ingredients"
        )
    finally:
        connection.close()

    backup_path = ingestion._create_verified_backup(database_path)

    assert backup_path is not None
    assert backup_path.is_file()
    assert ingestion._sha256(backup_path) == ingestion._sha256(database_path)
    backup = duckdb.connect(str(backup_path), read_only=True)
    try:
        assert backup.execute("SELECT product_count FROM catalog").fetchone() == (1,)
    finally:
        backup.close()
