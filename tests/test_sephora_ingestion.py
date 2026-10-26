from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import duckdb
import pytest

from src.ingestion import load_sephora_kaggle_to_duckdb as ingestion

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sephora"
FIXTURE_REVIEW_FILES = tuple(
    sorted(path.name for path in FIXTURE_DIR.glob("reviews_*.csv"))
)


def copy_fixture(tmp_path: Path) -> Path:
    destination = tmp_path / "dataset"
    shutil.copytree(FIXTURE_DIR, destination)
    return destination


def write_fixture_download_manifest(dataset_dir: Path) -> None:
    files = []
    for path in sorted(dataset_dir.glob("*.csv")):
        files.append(
            {
                "filename": path.name,
                "byte_size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (dataset_dir / ingestion.DOWNLOAD_MANIFEST).write_text(
        json.dumps(
            {
                "dataset_handle": ingestion.DATASET_ID,
                "downloaded_at": "2026-10-20T00:00:00+00:00",
                "local_path": str(dataset_dir),
                "files": files,
            }
        ),
        encoding="utf-8",
    )


def create_existing_database(database_path: Path) -> None:
    with duckdb.connect(str(database_path)) as connection:
        connection.execute("CREATE SCHEMA raw")
        connection.execute(
            "CREATE TABLE raw.raw_products (id VARCHAR, name VARCHAR)"
        )
        connection.execute(
            "INSERT INTO raw.raw_products VALUES ('old-1', 'Existing product')"
        )


def test_full_ingestion_preserves_source_reviews_and_writes_manifest(
    tmp_path: Path,
) -> None:
    dataset_dir = copy_fixture(tmp_path)
    database_path = tmp_path / "working.duckdb"
    create_existing_database(database_path)

    result = ingestion.ingest_sephora_dataset(dataset_dir, database_path)

    assert result.mode == "product_and_reviews"
    assert result.product_rows == 3
    assert result.review_rows == 5
    assert result.duplicate_review_rows == 1
    assert result.orphan_review_rows == 1
    assert result.complete_product_and_review_ingestion is True
    assert result.backup_path is not None and result.backup_path.is_file()

    with duckdb.connect(str(database_path), read_only=True) as connection:
        product_rows, distinct_ids = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT id) FROM raw.raw_products"
        ).fetchone()
        assert (product_rows, distinct_ids) == (3, 3)

        canonical = connection.execute(
            """
            SELECT id, brand, name, category, secondary_category,
                   tertiary_category, ingredients, price_usd, rating,
                   reviews, contains_fragrance
            FROM raw.raw_products
            WHERE id = 'p1'
            """
        ).fetchone()
        assert canonical == (
            "p1",
            "Brand A",
            "Serum One",
            "Skincare",
            "Treatments",
            "Serums",
            "Water, Glycerin",
            32.0,
            4.5,
            100,
            None,
        )

        source_columns = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'raw'
                  AND table_name = 'sephora_product_info'
                """
            ).fetchall()
        }
        assert {
            "primary_category",
            "secondary_category",
            "tertiary_category",
            "ingredients",
            "price_usd",
        } <= source_columns
        non_text_source_columns = connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'raw'
              AND table_name IN ('sephora_product_info', 'sephora_reviews')
              AND data_type <> 'VARCHAR'
            """
        ).fetchone()[0]
        assert non_text_source_columns == 0

        review_count, orphan_count, source_file_count = connection.execute(
            """
            SELECT
                COUNT(*),
                COUNT(*) FILTER (WHERE product_id = 'p999'),
                COUNT(DISTINCT source_filename)
            FROM raw.sephora_reviews
            """
        ).fetchone()
        assert (review_count, orphan_count, source_file_count) == (5, 1, 5)

        manifest = connection.execute(
            """
            SELECT dataset_id, dataset_url, ingestion_mode, source_filename,
                   file_bytes, sha256, row_count,
                   complete_product_and_review_ingestion
            FROM raw.sephora_ingestion_manifest
            ORDER BY source_role, source_filename
            """
        ).fetchall()
        assert len(manifest) == 6
        assert all(row[0] == ingestion.DATASET_ID for row in manifest)
        assert all(row[1] == ingestion.DATASET_URL for row in manifest)
        assert all(row[2] == "product_and_reviews" for row in manifest)
        assert all(row[7] is True for row in manifest)

    for row in manifest:
        filename, file_bytes, digest, row_count = row[3], row[4], row[5], row[6]
        source_path = dataset_dir / filename
        assert file_bytes == source_path.stat().st_size
        assert digest == hashlib.sha256(source_path.read_bytes()).hexdigest()
        expected_rows = 3 if filename == ingestion.PRODUCT_FILE else 1
        assert row_count == expected_rows


def test_download_manifest_metadata_is_recorded_by_ingestion(
    tmp_path: Path,
) -> None:
    dataset_dir = copy_fixture(tmp_path)
    write_fixture_download_manifest(dataset_dir)
    database_path = tmp_path / "download_metadata.duckdb"

    ingestion.ingest_sephora_dataset(dataset_dir, database_path)

    with duckdb.connect(str(database_path), read_only=True) as connection:
        downloaded_at, source_directory = connection.execute(
            """
            SELECT DISTINCT downloaded_at, source_directory
            FROM raw.sephora_ingestion_manifest
            """
        ).fetchone()
    assert downloaded_at is not None
    assert source_directory == str(dataset_dir.resolve())


def test_catalog_only_mode_is_explicit_and_removes_stale_reviews(
    tmp_path: Path,
) -> None:
    dataset_dir = tmp_path / "catalog"
    dataset_dir.mkdir()
    shutil.copy2(FIXTURE_DIR / ingestion.PRODUCT_FILE, dataset_dir)
    database_path = tmp_path / "catalog_only.duckdb"
    create_existing_database(database_path)
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            "CREATE TABLE raw.sephora_reviews (product_id VARCHAR)"
        )
        connection.execute("INSERT INTO raw.sephora_reviews VALUES ('stale')")

    result = ingestion.ingest_sephora_dataset(
        dataset_dir,
        database_path,
        catalog_only=True,
    )

    assert result.mode == "catalog_only"
    assert result.product_rows == 3
    assert result.review_rows == 0
    assert result.complete_product_and_review_ingestion is False
    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'raw' AND table_name = 'sephora_reviews'
            """
        ).fetchone()[0] == 0
        manifest = connection.execute(
            """
            SELECT ingestion_mode, row_count, complete_product_and_review_ingestion
            FROM raw.sephora_ingestion_manifest
            """
        ).fetchone()
        assert manifest == ("catalog_only", 3, False)


def test_catalog_only_manifest_records_partial_review_inventory(
    tmp_path: Path,
) -> None:
    dataset_dir = tmp_path / "partial_catalog"
    dataset_dir.mkdir()
    shutil.copy2(FIXTURE_DIR / ingestion.PRODUCT_FILE, dataset_dir)
    shutil.copy2(FIXTURE_DIR / FIXTURE_REVIEW_FILES[0], dataset_dir)
    database_path = tmp_path / "partial_catalog.duckdb"

    result = ingestion.ingest_sephora_dataset(
        dataset_dir,
        database_path,
        catalog_only=True,
    )

    assert result.available_review_files == (FIXTURE_REVIEW_FILES[0],)
    assert result.missing_review_files == ()
    with duckdb.connect(str(database_path), read_only=True) as connection:
        available, expected, missing = connection.execute(
            """
            SELECT available_review_files_json,
                   expected_review_files_json,
                   missing_review_files_json
            FROM raw.sephora_ingestion_manifest
            """
        ).fetchone()
        assert available == f'["{FIXTURE_REVIEW_FILES[0]}"]'
        assert expected == available
        assert missing == "[]"


def test_review_inventory_is_discovered_without_fixed_partition_names(
    tmp_path: Path,
) -> None:
    dataset_dir = tmp_path / "one_review_partition"
    dataset_dir.mkdir()
    shutil.copy2(FIXTURE_DIR / ingestion.PRODUCT_FILE, dataset_dir)
    shutil.copy2(
        FIXTURE_DIR / FIXTURE_REVIEW_FILES[0],
        dataset_dir / "reviews.csv",
    )
    (dataset_dir / "reviews.csv").rename(dataset_dir / "reviews_recent.csv")
    database_path = tmp_path / "dynamic_inventory.duckdb"

    result = ingestion.ingest_sephora_dataset(dataset_dir, database_path)

    assert result.available_review_files == ("reviews_recent.csv",)
    assert result.review_rows == 1
    assert result.missing_review_files == ()


@pytest.mark.parametrize(
    ("remove_file", "message"),
    [
        ("reviews_500-750.csv", "missing"),
        ("other.csv", "Unexpected CSV input files"),
    ],
)
def test_invalid_review_inventory_fails_before_database_write(
    tmp_path: Path,
    remove_file: str,
    message: str,
) -> None:
    dataset_dir = copy_fixture(tmp_path)
    if remove_file == "other.csv":
        (dataset_dir / remove_file).write_text(
            "product_id\np1\n",
            encoding="utf-8",
        )
    else:
        write_fixture_download_manifest(dataset_dir)
        (dataset_dir / remove_file).unlink()
    database_path = tmp_path / "preserved.duckdb"
    create_existing_database(database_path)

    with pytest.raises(ValueError, match=message):
        ingestion.ingest_sephora_dataset(dataset_dir, database_path)

    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute(
            "SELECT id, name FROM raw.raw_products"
        ).fetchall() == [("old-1", "Existing product")]


def test_duplicate_product_ids_roll_back_all_replacements(tmp_path: Path) -> None:
    dataset_dir = copy_fixture(tmp_path)
    product_path = dataset_dir / ingestion.PRODUCT_FILE
    lines = product_path.read_text(encoding="utf-8").splitlines()
    product_path.write_text(
        "\n".join([*lines, lines[1]]) + "\n",
        encoding="utf-8",
    )
    database_path = tmp_path / "duplicate_ids.duckdb"
    create_existing_database(database_path)

    with pytest.raises(ValueError, match="duplicate product_id"):
        ingestion.ingest_sephora_dataset(dataset_dir, database_path)

    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute(
            "SELECT id, name FROM raw.raw_products"
        ).fetchall() == [("old-1", "Existing product")]
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'raw' AND table_name = 'sephora_product_info'
            """
        ).fetchone()[0] == 0


def test_missing_required_product_column_is_reported_before_mutation(
    tmp_path: Path,
) -> None:
    dataset_dir = copy_fixture(tmp_path)
    product_path = dataset_dir / ingestion.PRODUCT_FILE
    rows = list(csv.reader(product_path.open(encoding="utf-8", newline="")))
    reduced_rows = [
        [value for index, value in enumerate(row) if index != 0]
        for row in rows
    ]
    with product_path.open("w", encoding="utf-8", newline="") as destination:
        csv.writer(destination).writerows(reduced_rows)
    database_path = tmp_path / "missing_column.duckdb"
    create_existing_database(database_path)

    with pytest.raises(ValueError, match="missing required columns: product_id"):
        ingestion.ingest_sephora_dataset(dataset_dir, database_path)

    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute(
            "SELECT id FROM raw.raw_products"
        ).fetchall() == [("old-1",)]


def test_malformed_numeric_product_values_are_counted_not_dropped(
    tmp_path: Path,
) -> None:
    dataset_dir = copy_fixture(tmp_path)
    product_path = dataset_dir / ingestion.PRODUCT_FILE
    rows = list(csv.DictReader(product_path.open(encoding="utf-8", newline="")))
    rows[0]["price_usd"] = "not-a-price"
    rows[0]["rating"] = "not-a-rating"
    rows[0]["reviews"] = "not-a-count"
    with product_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    database_path = tmp_path / "malformed_numeric.duckdb"

    result = ingestion.ingest_sephora_dataset(dataset_dir, database_path)

    assert result.product_rows == 3
    assert result.invalid_price_rows == 1
    assert result.invalid_product_rating_rows == 1
    assert result.invalid_aggregate_review_count_rows == 1
    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*), COUNT(price_usd) FROM raw.raw_products"
        ).fetchone() == (3, 2)
        assert connection.execute(
            "SELECT price_usd FROM raw.sephora_product_info WHERE product_id = 'p1'"
        ).fetchone()[0] == "not-a-price"


def test_numeric_boolean_recommendations_are_validated_as_zero_or_one(
    tmp_path: Path,
) -> None:
    dataset_dir = copy_fixture(tmp_path)
    for filename, value in (
        (FIXTURE_REVIEW_FILES[0], "1.0"),
        (FIXTURE_REVIEW_FILES[1], "2.0"),
    ):
        review_path = dataset_dir / filename
        rows = list(
            csv.DictReader(review_path.open(encoding="utf-8", newline=""))
        )
        rows[0]["is_recommended"] = value
        with review_path.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    result = ingestion.ingest_sephora_dataset(
        dataset_dir,
        tmp_path / "numeric_recommendation.duckdb",
    )

    assert result.invalid_review_recommendation_rows == 1


def test_repeated_ingestion_replaces_sources_without_duplicating_rows(
    tmp_path: Path,
) -> None:
    dataset_dir = copy_fixture(tmp_path)
    database_path = tmp_path / "idempotent.duckdb"

    first = ingestion.ingest_sephora_dataset(dataset_dir, database_path)
    second = ingestion.ingest_sephora_dataset(dataset_dir, database_path)

    assert (first.product_rows, first.review_rows) == (3, 5)
    assert (second.product_rows, second.review_rows) == (3, 5)
    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw.raw_products").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM raw.sephora_reviews").fetchone()[0] == 5
        assert connection.execute(
            "SELECT COUNT(*) FROM raw.sephora_ingestion_manifest"
        ).fetchone()[0] == 6


def test_csv_parse_failure_rolls_back_existing_source_tables(
    tmp_path: Path,
) -> None:
    dataset_dir = copy_fixture(tmp_path)
    review_path = dataset_dir / FIXTURE_REVIEW_FILES[0]
    header = review_path.read_text(encoding="utf-8").splitlines()[0]
    review_path.write_text(
        header + '\n"p1,a1,5,true,2024-01-01,unclosed text,Title\n',
        encoding="utf-8",
    )
    database_path = tmp_path / "parse_failure.duckdb"
    create_existing_database(database_path)

    with pytest.raises(duckdb.Error):
        ingestion.ingest_sephora_dataset(dataset_dir, database_path)

    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute(
            "SELECT id, name FROM raw.raw_products"
        ).fetchall() == [("old-1", "Existing product")]
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'raw' AND table_name = 'sephora_product_info'
            """
        ).fetchone()[0] == 0


def test_direct_production_database_write_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="production DuckDB is disabled"):
        ingestion.ingest_sephora_dataset(
            tmp_path / "not-needed",
            ingestion.PRODUCTION_DATABASE_PATH,
            catalog_only=True,
        )
