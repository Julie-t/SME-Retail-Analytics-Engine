"""Download and validate the Sephora Kaggle dataset with KaggleHub."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

DATASET_ID = "nadyinky/sephora-products-and-skincare-reviews"
PRODUCT_FILE = "product_info.csv"
DOWNLOAD_MANIFEST = "download_manifest.json"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "source" / "sephora_kaggle"
LOGGER = logging.getLogger(__name__)

PRODUCT_REQUIRED_COLUMNS = {
    "product_id",
    "product_name",
    "brand_name",
    "primary_category",
    "ingredients",
    "price_usd",
    "rating",
    "reviews",
}
REVIEW_REQUIRED_COLUMNS = {
    "product_id",
    "author_id",
    "rating",
    "is_recommended",
    "submission_time",
    "review_text",
    "review_title",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_header(path: Path) -> tuple[str, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            header = next(csv.reader(source), None)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(f"Cannot read CSV header from {path.name}: {error}") from error
    if not header:
        raise ValueError(f"{path.name} is empty or has an invalid CSV header.")
    normalized_header = tuple(
        column if column.strip() else f"column{index:02d}"
        for index, column in enumerate(header)
    )
    if len(normalized_header) != len(set(normalized_header)):
        raise ValueError(f"{path.name} contains duplicate column names.")
    return normalized_header


def _inventory(dataset_dir: Path) -> list[dict[str, str | int]]:
    if not dataset_dir.is_dir():
        raise FileNotFoundError(
            f"KaggleHub returned a dataset path that is not a directory: {dataset_dir}"
        )
    product_path = dataset_dir / PRODUCT_FILE
    review_paths = sorted(
        (
            path
            for path in dataset_dir.glob("reviews_*.csv")
            if path.is_file()
        ),
        key=lambda path: path.name.casefold(),
    )
    if not product_path.is_file():
        raise ValueError(f"Downloaded dataset is missing {PRODUCT_FILE}.")
    if not review_paths:
        raise ValueError("Downloaded dataset contains no reviews_*.csv source files.")

    product_header = set(_read_header(product_path))
    missing_product_columns = sorted(PRODUCT_REQUIRED_COLUMNS - product_header)
    if missing_product_columns:
        raise ValueError(
            f"{PRODUCT_FILE} is missing required columns: "
            + ", ".join(missing_product_columns)
        )

    review_header = _read_header(review_paths[0])
    missing_review_columns = sorted(set(REVIEW_REQUIRED_COLUMNS) - set(review_header))
    if missing_review_columns:
        raise ValueError(
            f"{review_paths[0].name} is missing required columns: "
            + ", ".join(missing_review_columns)
        )
    for review_path in review_paths[1:]:
        if _read_header(review_path) != review_header:
            raise ValueError(
                "Review CSV files have incompatible headers: "
                f"{review_path.name} does not match {review_paths[0].name}."
            )

    records: list[dict[str, str | int]] = []
    for path in (product_path, *review_paths):
        byte_size = path.stat().st_size
        if byte_size == 0:
            raise ValueError(f"Downloaded source file is empty: {path.name}.")
        records.append(
            {
                "filename": path.name,
                "byte_size": byte_size,
                "sha256": _sha256(path),
            }
        )
    return records


def _manifest_matches(dataset_dir: Path) -> bool:
    manifest_path = dataset_dir / DOWNLOAD_MANIFEST
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return (
            isinstance(manifest, dict)
            and manifest.get("dataset_handle") == DATASET_ID
            and manifest.get("files") == _inventory(dataset_dir)
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return False


def _download_error_message(error: Exception) -> str:
    error_name = type(error).__name__.casefold()
    message = str(error).casefold()
    if any(
        hint in error_name or hint in message
        for hint in ("consent", "terms of use", "accept terms")
    ):
        return (
            "Kaggle requires dataset consent or acceptance of its terms. Open the "
            "dataset page, accept the required terms with your account, and retry."
        )
    if any(
        hint in error_name or hint in message
        for hint in ("auth", "credential", "token", "unauthorized", "401", "login")
    ):
        return (
            "KaggleHub authentication failed. Configure Kaggle credentials using "
            "Kaggle's documented authentication methods, then retry. Credentials "
            "and tokens were not logged."
        )
    if any(
        hint in error_name or hint in message
        for hint in ("permission", "forbidden", "access denied", "403")
    ):
        return (
            "KaggleHub could not access the dataset or output directory. Check "
            "dataset access and local directory permissions."
        )
    return (
        "KaggleHub could not download the requested dataset. Check network access, "
        "dataset availability, Kaggle authentication, and consent status."
    )


def download_dataset(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    refresh: bool = False,
) -> Path:
    """Download once, validate source files, and return their containing directory."""
    target_dir = output_dir.expanduser().resolve()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PermissionError(
            f"Cannot create Kaggle dataset output directory {target_dir}; "
            "check its parent-directory permissions."
        ) from error

    if not refresh and _manifest_matches(target_dir):
        LOGGER.info("Reusing validated Kaggle dataset at %s.", target_dir)
        return target_dir

    try:
        import kagglehub
    except ImportError as error:
        raise RuntimeError(
            "KaggleHub is not installed. Install project dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from error

    try:
        downloaded_path = kagglehub.dataset_download(
            DATASET_ID,
            output_dir=str(target_dir),
            force_download=refresh,
        )
    except Exception as error:
        raise RuntimeError(_download_error_message(error)) from None

    returned_dir = Path(downloaded_path).expanduser().resolve()
    candidates = [returned_dir]
    if returned_dir != target_dir:
        candidates.append(target_dir)
    candidates.extend(
        sorted(
            {path.parent.resolve() for path in target_dir.rglob(PRODUCT_FILE)},
            key=str,
        )
    )
    dataset_dir: Path | None = None
    validation_errors: list[str] = []
    for candidate in candidates:
        try:
            _inventory(candidate)
        except (OSError, UnicodeError, ValueError) as error:
            validation_errors.append(str(error))
        else:
            dataset_dir = candidate
            break
    if dataset_dir is None:
        detail = validation_errors[-1] if validation_errors else "source files not found"
        raise ValueError(
            "KaggleHub returned an incomplete or incompatible dataset directory: "
            f"{detail}"
        )

    files = _inventory(dataset_dir)
    manifest = {
        "dataset_handle": DATASET_ID,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "local_path": str(dataset_dir),
        "files": files,
    }
    manifest_path = dataset_dir / DOWNLOAD_MANIFEST
    temporary_manifest = dataset_dir / f"{DOWNLOAD_MANIFEST}.tmp"
    try:
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary_manifest.replace(manifest_path)
    except OSError as error:
        raise OSError(
            f"Downloaded files are valid, but the audit manifest could not be "
            f"written to {manifest_path}. Check directory permissions."
        ) from error
    LOGGER.info(
        "Validated Kaggle dataset %s in %s (%s source files).",
        DATASET_ID,
        dataset_dir,
        len(files),
    )
    return dataset_dir


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Local destination for the KaggleHub dataset files.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force KaggleHub to download a fresh dataset revision.",
    )
    args = parser.parse_args(argv)
    print(download_dataset(args.output_dir, refresh=args.refresh))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
