from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.ingestion import download_sephora_kaggle as downloader
from src.ingestion import load_sephora_kaggle_to_duckdb as ingestion

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sephora"


def fake_kagglehub(
    monkeypatch: pytest.MonkeyPatch,
    callback: Any,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "kagglehub",
        SimpleNamespace(dataset_download=callback),
    )


def test_download_creates_directory_and_records_auditable_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, bool]] = []

    def dataset_download(
        handle: str,
        *,
        output_dir: str,
        force_download: bool,
    ) -> str:
        calls.append((handle, output_dir, force_download))
        shutil.copytree(FIXTURE_DIR, output_dir, dirs_exist_ok=True)
        return output_dir

    fake_kagglehub(monkeypatch, dataset_download)
    output_dir = tmp_path / "new" / "dataset"

    actual_dir = downloader.download_dataset(output_dir)

    manifest = json.loads(
        (actual_dir / downloader.DOWNLOAD_MANIFEST).read_text(encoding="utf-8")
    )
    assert actual_dir == output_dir.resolve()
    assert calls == [(downloader.DATASET_ID, str(actual_dir), False)]
    assert manifest["dataset_handle"] == downloader.DATASET_ID
    assert manifest["downloaded_at"]
    assert Path(manifest["local_path"]) == actual_dir
    assert len(manifest["files"]) == 6
    for record in manifest["files"]:
        path = actual_dir / record["filename"]
        assert record["byte_size"] == path.stat().st_size
        assert record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_validated_download_is_reused_unless_refresh_is_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def dataset_download(
        handle: str,
        *,
        output_dir: str,
        force_download: bool,
    ) -> str:
        del handle
        calls.append(force_download)
        shutil.copytree(FIXTURE_DIR, output_dir, dirs_exist_ok=True)
        return output_dir

    fake_kagglehub(monkeypatch, dataset_download)
    output_dir = tmp_path / "dataset"
    downloader.download_dataset(output_dir)
    downloader.download_dataset(output_dir)
    downloader.download_dataset(output_dir, refresh=True)

    assert calls == [False, True]


def test_incomplete_download_reports_missing_product_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def dataset_download(
        handle: str,
        *,
        output_dir: str,
        force_download: bool,
    ) -> str:
        del handle, force_download
        target = Path(output_dir)
        shutil.copy2(FIXTURE_DIR / "reviews_0-250.csv", target)
        return output_dir

    fake_kagglehub(monkeypatch, dataset_download)

    with pytest.raises(ValueError, match="missing product_info.csv"):
        downloader.download_dataset(tmp_path / "incomplete")


def test_unnamed_source_header_is_preserved_with_duckdb_column_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / "reviews_unnamed.csv"
    source.write_text(",author_id\n0,a1\n", encoding="utf-8")

    expected = ("column00", "author_id")
    assert downloader._read_header(source) == expected
    assert ingestion._read_header(source) == expected


def test_download_errors_are_reported_without_echoing_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def dataset_download(*args: Any, **kwargs: Any) -> str:
        del args, kwargs
        raise RuntimeError("Authentication failed for token secret-token-value")

    fake_kagglehub(monkeypatch, dataset_download)

    with pytest.raises(RuntimeError, match="KaggleHub authentication failed") as error:
        downloader.download_dataset(tmp_path / "dataset")

    assert "secret-token-value" not in str(error.value)
