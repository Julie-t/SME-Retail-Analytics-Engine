"""Load an already-downloaded Sephora Kaggle CSV dataset into DuckDB."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import duckdb
from dotenv import load_dotenv

DATASET_ID = "nadyinky/sephora-products-and-skincare-reviews"
DATASET_URL = "https://www.kaggle.com/datasets/nadyinky/sephora-products-and-skincare-reviews"
PRODUCT_FILE = "product_info.csv"
DOWNLOAD_MANIFEST = "download_manifest.json"
PRODUCT_REQUIRED_COLUMNS = frozenset(
    {
        "product_id",
        "product_name",
        "brand_name",
        "primary_category",
        "ingredients",
        "price_usd",
        "rating",
        "reviews",
    }
)
REVIEW_REQUIRED_COLUMNS = frozenset(
    {
        "product_id",
        "author_id",
        "rating",
        "is_recommended",
        "submission_time",
        "review_text",
        "review_title",
    }
)
PRODUCT_OPTIONAL_COLUMNS = {
    "brand_id": "VARCHAR",
    "secondary_category": "VARCHAR",
    "tertiary_category": "VARCHAR",
    "image_url": "VARCHAR",
    "price_usd": "DOUBLE",
    "rating": "DOUBLE",
    "reviews": "BIGINT",
    "loves_count": "BIGINT",
    "limited_edition": "BOOLEAN",
    "new": "BOOLEAN",
    "online_only": "BOOLEAN",
    "out_of_stock": "BOOLEAN",
    "sephora_exclusive": "BOOLEAN",
}
LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "source" / "sephora_kaggle"
PRODUCTION_DATABASE_PATH = (PROJECT_ROOT / "data" / "retail_engine.duckdb").resolve()


@dataclass(frozen=True)
class SourceFile:
    path: Path
    role: str
    columns: tuple[str, ...]
    byte_size: int
    sha256: str
    modified_time_ns: int


@dataclass(frozen=True)
class IngestionResult:
    mode: str
    product_rows: int
    review_rows: int
    available_review_files: tuple[str, ...]
    missing_review_files: tuple[str, ...]
    duplicate_review_rows: int
    orphan_review_rows: int
    invalid_review_rating_rows: int
    invalid_review_recommendation_rows: int
    invalid_price_rows: int
    invalid_product_rating_rows: int
    invalid_aggregate_review_count_rows: int
    complete_product_and_review_ingestion: bool
    backup_path: Path | None


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _read_header(path: Path) -> tuple[str, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            header = next(csv.reader(source), None)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(f"Cannot read CSV header from {path.name}: {error}") from error
    if not header:
        raise ValueError(f"CSV file {path.name} is empty or has no header row.")
    normalized_header = tuple(
        column if column.strip() else f"column{index:02d}"
        for index, column in enumerate(header)
    )
    if len(normalized_header) != len(set(normalized_header)):
        raise ValueError(f"CSV file {path.name} contains duplicate column names.")
    return normalized_header


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_source_file(path: Path, role: str) -> SourceFile:
    if not path.is_file():
        raise ValueError(f"Required {role} CSV file is missing: {path}")
    before = path.stat()
    source_file = SourceFile(
        path=path,
        role=role,
        columns=_read_header(path),
        byte_size=before.st_size,
        sha256=_sha256(path),
        modified_time_ns=before.st_mtime_ns,
    )
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise RuntimeError(f"Input file changed while being fingerprinted: {path.name}")
    return source_file


def _validate_required_columns(
    source_file: SourceFile,
    required_columns: frozenset[str],
) -> None:
    missing = sorted(required_columns.difference(source_file.columns))
    if missing:
        raise ValueError(
            f"{source_file.path.name} is missing required columns: "
            + ", ".join(missing)
        )


def _read_download_manifest(dataset_dir: Path) -> dict[str, object] | None:
    manifest_path = dataset_dir / DOWNLOAD_MANIFEST
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read {DOWNLOAD_MANIFEST}: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("dataset_handle") != DATASET_ID:
        raise ValueError(
            f"{DOWNLOAD_MANIFEST} does not identify the expected Kaggle dataset."
        )
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError(f"{DOWNLOAD_MANIFEST} has no valid file inventory.")
    for record in files:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("filename"), str)
            or not isinstance(record.get("sha256"), str)
        ):
            raise ValueError(f"{DOWNLOAD_MANIFEST} contains an invalid file record.")
    return manifest


def _discover_files(
    dataset_dir: Path,
    catalog_only: bool,
) -> tuple[
    SourceFile,
    tuple[SourceFile, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    if not dataset_dir.is_dir():
        raise FileNotFoundError(
            f"Sephora dataset directory does not exist: {dataset_dir}. "
            "Set SEPHORA_DATASET_DIR or pass --dataset-dir."
        )

    entries = [entry for entry in dataset_dir.iterdir() if entry.is_file()]
    product_matches = [
        entry for entry in entries if entry.name.casefold() == PRODUCT_FILE.casefold()
    ]
    if len(product_matches) != 1 or product_matches[0].name != PRODUCT_FILE:
        raise ValueError(
            f"Expected exactly one file named {PRODUCT_FILE!r} in {dataset_dir}."
        )

    review_entries = [
        entry
        for entry in entries
        if entry.name.casefold().startswith("reviews_")
        and entry.suffix.casefold() == ".csv"
    ]
    unexpected_csv_files = sorted(
        entry.name
        for entry in entries
        if entry.suffix.casefold() == ".csv"
        and entry.name != PRODUCT_FILE
        and entry not in review_entries
    )
    if unexpected_csv_files:
        raise ValueError(
            "Unexpected CSV input files: " + ", ".join(unexpected_csv_files)
        )
    folded_names: dict[str, list[str]] = {}
    for entry in review_entries:
        folded_names.setdefault(entry.name.casefold(), []).append(entry.name)
    duplicate_names = sorted(
        names for names in folded_names.values() if len(names) > 1
    )
    if duplicate_names:
        duplicates = "; ".join(", ".join(names) for names in duplicate_names)
        raise ValueError(f"Duplicate review input filenames (case-insensitive): {duplicates}.")

    review_entries.sort(key=lambda entry: entry.name.casefold())
    found_names = {entry.name for entry in review_entries}
    download_manifest = _read_download_manifest(dataset_dir)
    if download_manifest is not None:
        expected = tuple(
            sorted(
                (
                    str(record["filename"])
                    for record in download_manifest["files"]
                    if str(record["filename"]).casefold().startswith("reviews_")
                    and str(record["filename"]).casefold().endswith(".csv")
                ),
                key=str.casefold,
            )
        )
        expected_names = set(expected)
        missing = tuple(name for name in expected if name not in found_names)
        unexpected = tuple(sorted(found_names - expected_names, key=str.casefold))
        if missing or unexpected:
            raise ValueError(
                "Review CSV inventory does not match download_manifest.json "
                f"(missing: {', '.join(missing) or 'none'}; "
                f"unexpected: {', '.join(unexpected) or 'none'})."
            )
    else:
        expected = tuple(sorted(found_names, key=str.casefold))
        missing = ()
    if not catalog_only and not review_entries:
        raise ValueError(
            "Full product-and-review ingestion requires at least one reviews_*.csv file."
        )

    product_file = _inspect_source_file(product_matches[0], "product")
    _validate_required_columns(product_file, PRODUCT_REQUIRED_COLUMNS)

    all_review_files: list[SourceFile] = []
    for entry in review_entries:
        source_file = _inspect_source_file(entry, "review")
        _validate_required_columns(source_file, REVIEW_REQUIRED_COLUMNS)
        all_review_files.append(source_file)
    if all_review_files:
        header = all_review_files[0].columns
        for source_file in all_review_files[1:]:
            if source_file.columns != header:
                raise ValueError(
                    "Review CSV files must have identical column names and order; "
                    f"{source_file.path.name} differs from {all_review_files[0].path.name}."
                )

    if download_manifest is not None:
        manifest_files = {
            str(record["filename"]): record
            for record in download_manifest["files"]
        }
        for source_file in (product_file, *all_review_files):
            record = manifest_files.get(source_file.path.name)
            if (
                record is None
                or record.get("byte_size") != source_file.byte_size
                or record.get("sha256") != source_file.sha256
            ):
                raise ValueError(
                    "Source file does not match download_manifest.json: "
                    f"{source_file.path.name}."
                )

    review_files = () if catalog_only else tuple(all_review_files)
    available = tuple(source_file.path.name for source_file in all_review_files)
    return product_file, review_files, missing, available, expected


def _read_csv_to_table(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    path: Path,
) -> None:
    connection.execute(
        f"CREATE TEMP TABLE {_quote_identifier(table_name)} AS "
        "SELECT * FROM read_csv(?, header=true, all_varchar=true)",
        [str(path)],
    )


def _stage_review_files(
    connection: duckdb.DuckDBPyConnection,
    review_files: Sequence[SourceFile],
) -> None:
    for index, source_file in enumerate(review_files):
        if index == 0:
            connection.execute(
                """
                CREATE TEMP TABLE stage_sephora_reviews AS
                SELECT ?::VARCHAR AS source_filename, *
                FROM read_csv(?, header=true, all_varchar=true)
                """,
                [source_file.path.name, str(source_file.path)],
            )
        else:
            connection.execute(
                """
                INSERT INTO stage_sephora_reviews
                SELECT ?::VARCHAR AS source_filename, *
                FROM read_csv(?, header=true, all_varchar=true)
                """,
                [source_file.path.name, str(source_file.path)],
            )


def _product_select_expression(
    column: str,
    source_columns: set[str],
    target_type: str,
    alias: str,
) -> str:
    if column not in source_columns:
        expression = f"NULL::{target_type}"
    else:
        source = _quote_identifier(column)
        if target_type == "VARCHAR":
            expression = f"NULLIF({source}, '')"
        else:
            expression = f"TRY_CAST(NULLIF(TRIM({source}), '') AS {target_type})"
    return f"{expression} AS {_quote_identifier(alias)}"


def _create_canonical_products(
    connection: duckdb.DuckDBPyConnection,
    product_columns: tuple[str, ...],
) -> None:
    columns = set(product_columns)
    selections = [
        _product_select_expression("product_id", columns, "VARCHAR", "id"),
        _product_select_expression("brand_name", columns, "VARCHAR", "brand"),
        _product_select_expression("product_name", columns, "VARCHAR", "name"),
        _product_select_expression("brand_id", columns, "VARCHAR", "brand_id"),
        _product_select_expression("image_url", columns, "VARCHAR", "image_url"),
        _product_select_expression(
            "primary_category", columns, "VARCHAR", "category"
        ),
        "NULL::VARCHAR AS origin",
        *(
            f"NULL::BOOLEAN AS {_quote_identifier(name)}"
            for name in (
                "contains_fragrance",
                "contains_drying_alcohol",
                "contains_parabens",
                "contains_sulfates",
                "contains_silicones",
            )
        ),
        _product_select_expression("ingredients", columns, "VARCHAR", "ingredients"),
        *(
            _product_select_expression(name, columns, data_type, name)
            for name, data_type in PRODUCT_OPTIONAL_COLUMNS.items()
            if name != "brand_id"
        ),
        _product_select_expression(
            "price_usd", columns, "VARCHAR", "price_usd_raw"
        ),
        _product_select_expression("rating", columns, "VARCHAR", "rating_raw"),
        _product_select_expression("reviews", columns, "VARCHAR", "reviews_raw"),
        _product_select_expression(
            "loves_count", columns, "VARCHAR", "loves_count_raw"
        ),
    ]
    connection.execute(
        "CREATE OR REPLACE TABLE raw.raw_products AS SELECT "
        + ",\n".join(selections)
        + " FROM stage_sephora_product_info"
    )


def _validate_staged_products(
    connection: duckdb.DuckDBPyConnection,
) -> int:
    row_count, null_ids, duplicate_id_groups = connection.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) FILTER (WHERE NULLIF(TRIM(product_id), '') IS NULL),
            COUNT(*) - COUNT(DISTINCT product_id)
        FROM stage_sephora_product_info
        """
    ).fetchone()
    if row_count == 0:
        raise ValueError("The product catalogue is empty; refusing source replacement.")
    if null_ids:
        raise ValueError(
            f"Product CSV contains {null_ids} rows with missing product_id values."
        )
    if duplicate_id_groups:
        raise ValueError(
            "Product CSV contains duplicate product_id values "
            f"({duplicate_id_groups} duplicate rows); no rows were deduplicated."
        )
    return int(row_count)


def _validate_staged_reviews(
    connection: duckdb.DuckDBPyConnection,
    review_columns: tuple[str, ...],
) -> tuple[int, int, int, int, int]:
    review_rows, null_ids = connection.execute(
        """
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE NULLIF(TRIM(product_id), '') IS NULL)
        FROM stage_sephora_reviews
        """
    ).fetchone()
    if null_ids:
        raise ValueError(
            f"Review CSVs contain {null_ids} rows with missing product_id values."
        )

    quoted = ", ".join(_quote_identifier(column) for column in review_columns)
    duplicate_review_rows = connection.execute(
        f"""
        SELECT COALESCE(SUM(duplicate_count - 1), 0)
        FROM (
            SELECT COUNT(*) AS duplicate_count
            FROM stage_sephora_reviews
            GROUP BY {quoted}
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    orphan_review_rows = connection.execute(
        """
        SELECT COUNT(*)
        FROM stage_sephora_reviews AS reviews
        WHERE NOT EXISTS (
            SELECT 1
            FROM stage_sephora_product_info AS products
            WHERE products.product_id = reviews.product_id
        )
        """
    ).fetchone()[0]
    invalid_review_rating_rows = connection.execute(
        """
        SELECT COUNT(*)
        FROM stage_sephora_reviews
        WHERE NULLIF(TRIM(rating), '') IS NOT NULL
          AND TRY_CAST(TRIM(rating) AS DOUBLE) IS NULL
        """
    ).fetchone()[0]
    invalid_review_recommendation_rows = connection.execute(
        """
        SELECT COUNT(*)
        FROM stage_sephora_reviews
        WHERE NULLIF(TRIM(is_recommended), '') IS NOT NULL
          AND CASE
                WHEN TRY_CAST(TRIM(is_recommended) AS DOUBLE) IS NOT NULL
                THEN TRY_CAST(TRIM(is_recommended) AS DOUBLE) NOT IN (0, 1)
                ELSE TRY_CAST(TRIM(is_recommended) AS BOOLEAN) IS NULL
              END
        """
    ).fetchone()[0]
    return (
        int(review_rows),
        int(duplicate_review_rows),
        int(orphan_review_rows),
        int(invalid_review_rating_rows),
        int(invalid_review_recommendation_rows),
    )


def _count_invalid_numeric_values(
    connection: duckdb.DuckDBPyConnection,
    column: str,
    target_type: str,
) -> int:
    quoted = _quote_identifier(column)
    return int(
        connection.execute(
            f"""
            SELECT COUNT(*)
            FROM stage_sephora_product_info
            WHERE NULLIF(TRIM({quoted}), '') IS NOT NULL
              AND TRY_CAST(TRIM({quoted}) AS {target_type}) IS NULL
            """
        ).fetchone()[0]
    )


def _file_row_counts(
    connection: duckdb.DuckDBPyConnection,
    review_files: Sequence[SourceFile],
) -> dict[str, int]:
    counts = {
        PRODUCT_FILE: int(
            connection.execute(
                "SELECT COUNT(*) FROM stage_sephora_product_info"
            ).fetchone()[0]
        ),
        **{source_file.path.name: 0 for source_file in review_files},
    }
    if review_files:
        counts.update(
            {
                filename: int(row_count)
                for filename, row_count in connection.execute(
                    """
                    SELECT source_filename, COUNT(*)
                    FROM stage_sephora_reviews
                    GROUP BY source_filename
                    """
                ).fetchall()
            }
        )
    return counts


def _check_inputs_unchanged(source_files: Sequence[SourceFile]) -> None:
    for source_file in source_files:
        current = source_file.path.stat()
        if (
            current.st_size != source_file.byte_size
            or current.st_mtime_ns != source_file.modified_time_ns
            or _sha256(source_file.path) != source_file.sha256
        ):
            raise RuntimeError(
                f"Input file changed during ingestion: {source_file.path.name}"
            )


def _write_manifest(
    connection: duckdb.DuckDBPyConnection,
    source_files: Sequence[SourceFile],
    row_counts: dict[str, int],
    mode: str,
    product_rows: int,
    review_rows: int,
    duplicate_review_rows: int,
    orphan_review_rows: int,
    invalid_review_rating_rows: int,
    invalid_review_recommendation_rows: int,
    invalid_price_rows: int,
    invalid_product_rating_rows: int,
    invalid_aggregate_review_count_rows: int,
    available_review_files: tuple[str, ...],
    expected_review_files: tuple[str, ...],
    missing_review_files: tuple[str, ...],
    downloaded_at: str | None,
    source_directory: str,
) -> None:
    complete = mode == "product_and_reviews"
    ingested_at = datetime.now(timezone.utc)
    records = [
        (
            DATASET_ID,
            DATASET_URL,
            mode,
            source_file.path.name,
            source_file.role,
            source_file.byte_size,
            source_file.sha256,
            row_counts[source_file.path.name],
            ingested_at,
            downloaded_at,
            source_directory,
            json.dumps(available_review_files),
            json.dumps(expected_review_files),
            json.dumps(missing_review_files),
            product_rows,
            review_rows,
            duplicate_review_rows,
            orphan_review_rows,
            invalid_review_rating_rows,
            invalid_review_recommendation_rows,
            invalid_price_rows,
            invalid_product_rating_rows,
            invalid_aggregate_review_count_rows,
            complete,
        )
        for source_file in source_files
    ]
    connection.execute(
        """
        CREATE OR REPLACE TABLE raw.sephora_ingestion_manifest (
            dataset_id VARCHAR,
            dataset_url VARCHAR,
            ingestion_mode VARCHAR,
            source_filename VARCHAR,
            source_role VARCHAR,
            file_bytes BIGINT,
            sha256 VARCHAR,
            row_count BIGINT,
            ingested_at TIMESTAMPTZ,
            downloaded_at TIMESTAMPTZ,
            source_directory VARCHAR,
            available_review_files_json VARCHAR,
            expected_review_files_json VARCHAR,
            missing_review_files_json VARCHAR,
            product_rows BIGINT,
            review_rows BIGINT,
            duplicate_review_rows BIGINT,
            orphan_review_rows BIGINT,
            invalid_review_rating_rows BIGINT,
            invalid_review_recommendation_rows BIGINT,
            invalid_price_rows BIGINT,
            invalid_product_rating_rows BIGINT,
            invalid_aggregate_review_count_rows BIGINT,
            complete_product_and_review_ingestion BOOLEAN
        )
        """
    )
    connection.executemany(
        "INSERT INTO raw.sephora_ingestion_manifest VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        records,
    )


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
    finally:
        backup_connection.close()
    return backup_path


def ingest_sephora_dataset(
    dataset_dir: Path,
    database_path: Path,
    *,
    catalog_only: bool = False,
) -> IngestionResult:
    """Validate and atomically replace staged Sephora source relations."""
    resolved_database_path = database_path.expanduser().resolve()
    if resolved_database_path == PRODUCTION_DATABASE_PATH:
        raise ValueError(
            "Direct ingestion into the configured production DuckDB is disabled. "
            "Use an isolated database copy and a separately approved promotion."
        )

    (
        product_file,
        review_files,
        missing_review_files,
        available_review_files,
        expected_review_files,
    ) = _discover_files(
        dataset_dir.expanduser().resolve(),
        catalog_only,
    )
    resolved_dataset_dir = dataset_dir.expanduser().resolve()
    download_manifest = _read_download_manifest(resolved_dataset_dir)
    downloaded_at = (
        str(download_manifest["downloaded_at"])
        if download_manifest is not None
        and isinstance(download_manifest.get("downloaded_at"), str)
        else None
    )
    source_files = (product_file, *review_files)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = _create_verified_backup(resolved_database_path)

    connection = duckdb.connect(str(resolved_database_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        connection.execute("CREATE SCHEMA IF NOT EXISTS raw")
        _read_csv_to_table(connection, "stage_sephora_product_info", product_file.path)
        _stage_review_files(connection, review_files)

        product_rows = _validate_staged_products(connection)
        if review_files:
            (
                review_rows,
                duplicate_review_rows,
                orphan_review_rows,
                invalid_review_rating_rows,
                invalid_review_recommendation_rows,
            ) = (
                _validate_staged_reviews(
                    connection,
                    review_files[0].columns,
                )
            )
        else:
            review_rows = duplicate_review_rows = orphan_review_rows = 0
            invalid_review_rating_rows = invalid_review_recommendation_rows = 0

        invalid_price_rows = _count_invalid_numeric_values(
            connection, "price_usd", "DOUBLE"
        )
        invalid_product_rating_rows = _count_invalid_numeric_values(
            connection, "rating", "DOUBLE"
        )
        invalid_aggregate_review_count_rows = _count_invalid_numeric_values(
            connection, "reviews", "BIGINT"
        )

        connection.execute(
            "CREATE OR REPLACE TABLE raw.sephora_product_info AS "
            "SELECT * FROM stage_sephora_product_info"
        )
        if review_files:
            connection.execute(
                "CREATE OR REPLACE TABLE raw.sephora_reviews AS "
                "SELECT * FROM stage_sephora_reviews"
            )
        else:
            connection.execute("DROP TABLE IF EXISTS raw.sephora_reviews")

        _create_canonical_products(connection, product_file.columns)
        row_counts = _file_row_counts(connection, review_files)
        _check_inputs_unchanged(source_files)
        _write_manifest(
            connection,
            source_files,
            row_counts,
            "catalog_only" if catalog_only else "product_and_reviews",
            product_rows,
            review_rows,
            duplicate_review_rows,
            orphan_review_rows,
            invalid_review_rating_rows,
            invalid_review_recommendation_rows,
            invalid_price_rows,
            invalid_product_rating_rows,
            invalid_aggregate_review_count_rows,
            available_review_files,
            expected_review_files,
            missing_review_files,
            downloaded_at,
            str(resolved_dataset_dir),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return IngestionResult(
        mode="catalog_only" if catalog_only else "product_and_reviews",
        product_rows=product_rows,
        review_rows=review_rows,
        available_review_files=available_review_files,
        missing_review_files=missing_review_files,
        duplicate_review_rows=duplicate_review_rows,
        orphan_review_rows=orphan_review_rows,
        invalid_review_rating_rows=invalid_review_rating_rows,
        invalid_review_recommendation_rows=invalid_review_recommendation_rows,
        invalid_price_rows=invalid_price_rows,
        invalid_product_rating_rows=invalid_product_rating_rows,
        invalid_aggregate_review_count_rows=invalid_aggregate_review_count_rows,
        complete_product_and_review_ingestion=not catalog_only,
        backup_path=backup_path,
    )


def main(argv: Sequence[str] | None = None) -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path(os.environ.get("SEPHORA_DATASET_DIR", DEFAULT_DATASET_DIR)),
        help="Directory containing product_info.csv and the expected review CSVs.",
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        required=True,
        help="Explicit isolated DuckDB path; the configured production database is refused.",
    )
    parser.add_argument(
        "--catalog-only",
        action="store_true",
        help="Load products only and mark product-plus-review ingestion incomplete.",
    )
    args = parser.parse_args(argv)
    result = ingest_sephora_dataset(
        args.dataset_dir,
        args.database_path,
        catalog_only=args.catalog_only,
    )
    LOGGER.info(
        "Loaded %s product rows and %s review rows (%s; complete=%s). "
        "Duplicate review rows=%s, orphan review rows=%s; backup=%s",
        result.product_rows,
        result.review_rows,
        result.mode,
        result.complete_product_and_review_ingestion,
        result.duplicate_review_rows,
        result.orphan_review_rows,
        result.backup_path,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
