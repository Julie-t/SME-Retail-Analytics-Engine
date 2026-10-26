"""Legacy Beauty API adapter; Sephora Kaggle ingestion is now the default source."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import duckdb
import polars as pl
import requests
from dotenv import load_dotenv

API_BASE_URL = "https://api.thebeautyapi.com/v1"
MAX_PAGES = 51
PAGE_SIZE = 20
BATCH_SIZE = 50
MIN_REQUEST_INTERVAL_SECONDS = 0.2
MAX_429_RETRIES = 5
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 30

LOGGER = logging.getLogger(__name__)


def _request_with_rate_limit_retry(
    session: requests.Session,
    method: str,
    url: str,
    **kwargs: Any,
) -> requests.Response:
    for attempt in range(MAX_429_RETRIES + 1):
        last_request_at = getattr(session, "_beauty_api_last_request_at", None)
        if last_request_at is not None:
            elapsed = time.monotonic() - last_request_at
            if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
                time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        setattr(session, "_beauty_api_last_request_at", time.monotonic())
        response = session.request(
            method,
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )
        if response.status_code != 429:
            response.raise_for_status()
            return response

        if attempt == MAX_429_RETRIES:
            response.raise_for_status()

        delay = min(BACKOFF_BASE_SECONDS * (2**attempt), BACKOFF_MAX_SECONDS)
        LOGGER.warning(
            "The Beauty API rate-limited the request; retrying in %.1f seconds "
            "(attempt %s of %s).",
            delay,
            attempt + 1,
            MAX_429_RETRIES,
        )
        time.sleep(delay)

    raise RuntimeError("The Beauty API request retry loop exited unexpectedly.")


def _fetch_slim_products(session: requests.Session) -> list[dict[str, Any]]:
    slim_products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    expected_total: int | None = None
    pages_fetched = 0

    for page in range(1, MAX_PAGES + 1):
        response = _request_with_rate_limit_retry(
            session,
            "GET",
            f"{API_BASE_URL}/products",
            params={"page": page},
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected product listing response on page {page}.")

        results = payload.get("results")
        pagination = payload.get("pagination")
        if not isinstance(results, list) or not isinstance(pagination, dict):
            raise ValueError(f"Missing results or pagination in page {page} response.")
        reported_page = pagination.get("page")
        total = pagination.get("total")
        has_more = pagination.get("has_more")
        if reported_page != page:
            raise ValueError(f"Unexpected pagination.page on page {page} response.")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise ValueError(f"Missing valid pagination.total on page {page}.")
        if not isinstance(has_more, bool):
            raise ValueError(f"Missing boolean pagination.has_more on page {page}.")
        if expected_total is None:
            expected_total = total
            if expected_total > MAX_PAGES * PAGE_SIZE:
                raise RuntimeError(
                    f"The API reports {expected_total} products, but its documented "
                    f"page limit can return at most {MAX_PAGES * PAGE_SIZE} products "
                    "per query. Use documented filters to partition the catalog; "
                    "refusing to fetch details or replace the existing catalog."
                )
        elif total != expected_total:
            raise ValueError(
                "pagination.total changed during extraction; refusing an "
                "inconsistent catalog snapshot."
            )

        expected_pages = max(1, (expected_total + PAGE_SIZE - 1) // PAGE_SIZE)
        expected_page_count = min(
            PAGE_SIZE,
            max(0, expected_total - ((page - 1) * PAGE_SIZE)),
        )
        expected_has_more = page < expected_pages
        if len(results) != expected_page_count or has_more != expected_has_more:
            raise RuntimeError(
                f"Page {page} does not match its pagination manifest "
                f"(expected {expected_page_count} results; "
                f"has_more={expected_has_more})."
            )

        for product in results:
            if not isinstance(product, dict):
                raise ValueError(f"Invalid product record on page {page}.")
            product_id = product.get("id")
            if not isinstance(product_id, str) or not product_id:
                raise ValueError(f"Product without a valid id on page {page}.")
            if product_id in seen_ids:
                raise ValueError(
                    f"Duplicate product ID across listing pages: {product_id}."
                )
            slim_products.append(product)
            seen_ids.add(product_id)

        pages_fetched = page
        LOGGER.info(
            "Fetched page %s (%s products; %s unique so far).",
            page,
            len(results),
            len(slim_products),
        )
        if not has_more:
            break

    if expected_total is None or len(slim_products) != expected_total:
        raise RuntimeError(
            "The unique listing count does not match pagination.total; "
            "refusing to use an incomplete extract."
        )
    LOGGER.info(
        "Validated listing manifest: %s pages, %s expected and unique products.",
        pages_fetched,
        expected_total,
    )
    return slim_products


def _validate_full_product(product: dict[str, Any]) -> None:
    for field in ("id", "brand", "name"):
        value = product.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Full product record is missing required non-empty field {field!r}."
            )

    boolean_fields = (
        "contains_fragrance",
        "contains_drying_alcohol",
        "contains_parabens",
        "contains_sulfates",
        "contains_silicones",
    )
    for field in boolean_fields:
        if not isinstance(product.get(field), bool):
            raise ValueError(
                f"Full product record is missing boolean field {field!r}."
            )

    ingredients = product.get("ingredients")
    if not isinstance(ingredients, list):
        raise ValueError("Full product record must contain an ingredient list.")
    for ingredient in ingredients:
        if not isinstance(ingredient, dict):
            raise ValueError("Ingredient payload entries must be objects.")
        name = ingredient.get("name")
        position = ingredient.get("position")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Ingredient payload entry has no valid normalized name.")
        if (
            not isinstance(position, int)
            or isinstance(position, bool)
            or position < 0
        ):
            raise ValueError("Ingredient payload entry has no valid position.")


def _fetch_full_products(
    session: requests.Session,
    slim_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    product_ids = [str(product["id"]) for product in slim_products]
    full_products: list[dict[str, Any]] = []

    for start in range(0, len(product_ids), BATCH_SIZE):
        batch_ids = product_ids[start : start + BATCH_SIZE]
        response = _request_with_rate_limit_retry(
            session,
            "POST",
            f"{API_BASE_URL}/products/batch",
            json={"ids": batch_ids},
        )
        batch_products = response.json()
        if not isinstance(batch_products, list) or len(batch_products) != len(batch_ids):
            raise ValueError(
                "Batch response must be a list with one entry per requested product."
            )

        requested_ids = set(batch_ids)
        received_ids: set[str] = set()
        for product in batch_products:
            if product is None:
                raise ValueError(
                    "The API returned no details for a requested product; "
                    "refusing to replace the existing catalog with an incomplete extract."
                )
            if not isinstance(product, dict):
                raise ValueError("Invalid product record in batch response.")
            product_id = product.get("id")
            if not isinstance(product_id, str) or product_id not in requested_ids:
                raise ValueError(
                    "Batch response contained a missing, invalid, or unrequested product ID."
                )
            if product_id in received_ids:
                raise ValueError(
                    "Batch response contained a duplicate product ID; "
                    "refusing to replace the existing catalog."
                )
            _validate_full_product(product)
            received_ids.add(product_id)

            normalized = dict(product)
            normalized["ingredients"] = json.dumps(
                normalized["ingredients"],
                ensure_ascii=False,
            )
            full_products.append(normalized)

        if received_ids != requested_ids:
            raise ValueError(
                "Batch response did not contain exactly the requested product IDs."
            )
        if [product["id"] for product in batch_products] != batch_ids:
            raise ValueError(
                "Batch response order did not match the documented request order."
            )

        LOGGER.info(
            "Fetched full details for batch %s-%s (%s records).",
            start + 1,
            start + len(batch_ids),
            len(batch_products),
        )

    return full_products


def _validate_products_frame(
    frame: pl.DataFrame,
    expected_count: int,
) -> None:
    if expected_count <= 0:
        raise ValueError("Refusing to replace the catalog with an empty extract.")
    if frame.height != expected_count:
        raise ValueError(
            f"Prepared product count {frame.height} does not match "
            f"the expected count {expected_count}."
        )
    required_columns = {
        "id",
        "brand",
        "name",
        "ingredients",
        "contains_fragrance",
        "contains_drying_alcohol",
        "contains_parabens",
        "contains_sulfates",
        "contains_silicones",
    }
    missing_columns = required_columns.difference(frame.columns)
    if missing_columns:
        raise ValueError(
            "Prepared product frame is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    product_ids = frame.get_column("id")
    if product_ids.null_count() or product_ids.n_unique() != expected_count:
        raise ValueError("Prepared product IDs must be unique and non-null.")
    for field in ("brand", "name", "ingredients"):
        if frame.get_column(field).null_count():
            raise ValueError(
                f"Prepared product field {field!r} must be non-null."
            )
    for field in (
        "contains_fragrance",
        "contains_drying_alcohol",
        "contains_parabens",
        "contains_sulfates",
        "contains_silicones",
    ):
        values = frame.get_column(field).to_list()
        if any(not isinstance(value, bool) for value in values):
            raise ValueError(f"Prepared product field {field!r} must be boolean.")

    for ingredients_json in frame.get_column("ingredients").to_list():
        try:
            ingredients = json.loads(ingredients_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("Prepared ingredient payload is not valid JSON.") from error
        if not isinstance(ingredients, list):
            raise ValueError("Prepared ingredient payload must encode a JSON array.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_verified_backup(database_path: Path) -> Path | None:
    if not database_path.is_file():
        return None

    backup_directory = database_path.parent / "backups"
    backup_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_directory / f"{database_path.stem}_{timestamp}.duckdb"
    if backup_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup {backup_path}.")

    source_hash = _sha256(database_path)
    shutil.copy2(database_path, backup_path)
    if _sha256(backup_path) != source_hash:
        raise RuntimeError(f"Database backup checksum verification failed: {backup_path}")

    backup_connection = duckdb.connect(":memory:")
    try:
        backup_literal = str(backup_path).replace("'", "''")
        catalog_name = database_path.stem.replace('"', '""')
        backup_connection.execute(
            f'ATTACH \'{backup_literal}\' AS "{catalog_name}" (READ_ONLY)'
        )
        raw_table_exists = backup_connection.execute(
            f"""
            SELECT COUNT(*)
            FROM duckdb_tables()
            WHERE database_name = '{database_path.stem.replace("'", "''")}'
                AND schema_name = 'raw'
                AND table_name = 'raw_products'
            """
        ).fetchone()[0]
        if raw_table_exists:
            backup_connection.execute(
                f'SELECT COUNT(*) FROM "{catalog_name}".raw.raw_products'
            ).fetchone()
    finally:
        backup_connection.close()
    return backup_path


def _write_frame(
    connection: duckdb.DuckDBPyConnection,
    frame: pl.DataFrame,
    table_name: str,
    view_name: str,
) -> None:
    connection.register(view_name, frame)
    try:
        connection.execute(
            f"CREATE OR REPLACE TABLE raw.{table_name} AS SELECT * FROM {view_name}"
        )
    finally:
        connection.unregister(view_name)


def _verify_raw_products(
    connection: duckdb.DuckDBPyConnection,
    expected_count: int,
) -> None:
    row_count, unique_ids, null_ids, invalid_ingredients = connection.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT id),
            COUNT(*) FILTER (WHERE id IS NULL),
            COUNT(*) FILTER (
                WHERE ingredients IS NULL OR NOT json_valid(ingredients)
            )
        FROM raw.raw_products
        """
    ).fetchone()
    if (
        row_count != expected_count
        or unique_ids != expected_count
        or null_ids != 0
        or invalid_ingredients != 0
    ):
        raise RuntimeError(
            "Written raw.raw_products failed post-write verification "
            f"(rows={row_count}, unique_ids={unique_ids}, null_ids={null_ids}, "
            f"invalid_ingredients={invalid_ingredients}, expected={expected_count})."
        )


def _replace_raw_products(
    connection: duckdb.DuckDBPyConnection,
    frame: pl.DataFrame,
    expected_count: int,
) -> None:
    _validate_products_frame(frame, expected_count)
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute("CREATE SCHEMA IF NOT EXISTS raw")
        _write_frame(connection, frame, "raw_products", "raw_products_frame")
        _verify_raw_products(connection, expected_count)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _products_frame(products: list[dict[str, Any]]) -> pl.DataFrame:
    if products:
        return pl.from_dicts(products, infer_schema_length=None, strict=False)
    return pl.DataFrame(
        schema={
            "id": pl.String,
            "brand": pl.String,
            "name": pl.String,
            "image_url": pl.String,
            "category": pl.String,
            "origin": pl.String,
            "contains_fragrance": pl.Boolean,
            "contains_drying_alcohol": pl.Boolean,
            "contains_parabens": pl.Boolean,
            "contains_sulfates": pl.Boolean,
            "contains_silicones": pl.Boolean,
            "ingredients": pl.String,
        }
    )


def _load_local_csvs(
    connection: duckdb.DuckDBPyConnection,
    raw_dir: Path,
) -> None:
    for filename, table_name in (
        ("sales.csv", "raw_sales"),
        ("inventory.csv", "raw_inventory"),
    ):
        csv_path = raw_dir / filename
        if not csv_path.is_file():
            LOGGER.info("Skipping missing optional CSV file: %s", csv_path)
            continue

        frame = pl.read_csv(csv_path)
        _write_frame(connection, frame, table_name, f"{table_name}_frame")
        LOGGER.info("Loaded %s rows from %s into raw.%s.", frame.height, csv_path, table_name)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Deprecated Beauty API loader; KaggleHub is the default source."
    )
    parser.add_argument(
        "--allow-legacy-beauty-api",
        action="store_true",
        help="Explicitly opt in to the deprecated Beauty API loader.",
    )
    args = parser.parse_args(argv)
    if not args.allow_legacy_beauty_api:
        parser.error(
            "This loader is deprecated and disabled by default. "
            "Use the KaggleHub downloader and ingestion pipeline instead."
        )

    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env", override=False)

    api_key = os.environ.get("BEAUTY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set BEAUTY_API_KEY in the project-root .env file or environment "
            "before ingestion."
        )

    database_path = project_root / "data" / "retail_engine.duckdb"
    raw_dir = project_root / "data" / "raw"
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:
        session.headers.update(
            {
                "x-api-key": api_key,
                "Accept": "application/json",
            }
        )
        slim_products = _fetch_slim_products(session)
        full_products = _fetch_full_products(session, slim_products)

    if len(full_products) != len(slim_products):
        raise RuntimeError(
            "Full detail record count does not match the validated listing manifest."
        )
    products_frame = _products_frame(full_products)
    _validate_products_frame(products_frame, len(slim_products))
    backup_path = _create_verified_backup(database_path)
    if backup_path is not None:
        LOGGER.info(
            "Created and verified pre-ingestion database backup: %s",
            backup_path,
        )

    connection = duckdb.connect(str(database_path))
    try:
        _replace_raw_products(
            connection,
            products_frame,
            len(slim_products),
        )
        LOGGER.info(
            "Verified and committed %s full products into %s.",
            len(slim_products),
            database_path,
        )
        _load_local_csvs(connection, raw_dir)
    finally:
        connection.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
