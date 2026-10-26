# Deterministic SME Retail Analytics Engine

Local-first catalogue analytics using DuckDB, dbt, Polars, and FastAPI. The
default catalogue source is a local download of
[Kaggle's Sephora Products and Skincare Reviews dataset](https://www.kaggle.com/datasets/nadyinky/sephora-products-and-skincare-reviews).
The optional Groq-backed assistant is an additive interface to allowlisted
deterministic catalogue and review metrics; it does not replace or calculate
those metrics.

## Install and configure

`requirements.txt` contains runtime dependencies, including KaggleHub.
`requirements-dev.txt` adds pytest and HTTP test dependencies:

```powershell
python -m pip install -r requirements-dev.txt
```

The Kaggle dataset is
[Sephora Products and Skincare Reviews](https://www.kaggle.com/datasets/nadyinky/sephora-products-and-skincare-reviews),
handle `nadyinky/sephora-products-and-skincare-reviews`. Configure KaggleHub
authentication using Kaggle's supported credentials for your account. If Kaggle
requires dataset terms or consent, visit the dataset page, accept them while
signed in, and retry. Do not put Kaggle tokens in source code, command
arguments, logs, or Git. `.env` is ignored; the downloader does not print or
persist credentials.

`RETAIL_ENGINE_DB_PATH` selects the DuckDB file used by the serving API.
`SEPHORA_DATASET_DIR` optionally selects another local dataset directory; its
default is `data\source\sephora_kaggle\`. Downloading never opens DuckDB.

The optional assistant reads `GROQ_API_KEY`, `GROQ_MODEL`,
`GROQ_TIMEOUT_SECONDS`, and `GROQ_MAX_RETRIES` from the API process environment.
The defaults are `llama-3.3-70b-versatile`, 30 seconds, and 2 retries. Copy
`.env.example` as a reference, but note the application does not automatically
load `.env`; configure the variables in the process environment instead. Keep
the API key out of source control, command arguments, and logs. Invalid timeout
or retry values are reported as configuration errors.

## Download and ingest the Kaggle files

Download programmatically with KaggleHub; importing either ingestion module
does not make a network request:

```powershell
python -m src.ingestion.download_sephora_kaggle
```

The downloader creates `data\source\sephora_kaggle\`, calls
`kagglehub.dataset_download()` for the dataset handle above, validates the
returned directory, and reports the actual containing path. A validated
download with a matching manifest is reused on later runs. To explicitly
request a fresh KaggleHub download:

```powershell
python -m src.ingestion.download_sephora_kaggle --refresh
```

An alternate local destination can be selected with `--output-dir`. Download
authentication failures, required consent, access/permission failures, and
incomplete source inventories produce actionable errors; exception text that
could contain credentials is not echoed.

The downloader requires `product_info.csv` and one or more `reviews_*.csv`
files. It validates required headers and review-header compatibility, but does
not assume a fixed review partition count or hard-code dataset row counts.
Ingestion revalidates the discovered source files against the download
inventory. `download_manifest.json` records the dataset handle, download
timestamp, actual local path, each filename, byte size, and SHA-256 checksum.
The DuckDB ingestion manifest additionally records ingestion timestamp,
per-file actual row counts, source path, checksums, review inventory, and
duplicate/orphan/parse-quality counts.

### Load an existing download into an isolated warehouse

Download and ingestion are separate operations. Ingestion requires an explicit
DuckDB path and refuses the repository's production path. First make a fresh
working copy of production and compare its fingerprint:

```powershell
$source = (Resolve-Path data\retail_engine.duckdb).Path
$isolated = Join-Path $env:TEMP 'retail_engine_sephora_working.duckdb'
Copy-Item $source $isolated
Get-FileHash $source -Algorithm SHA256
Get-FileHash $isolated -Algorithm SHA256
python -m src.ingestion.load_sephora_kaggle_to_duckdb `
  --dataset-dir data\source\sephora_kaggle `
  --database-path $isolated
```

Use `--catalog-only` only when intentionally loading products without review
rows. The target must still be explicit and isolated:

```powershell
python -m src.ingestion.load_sephora_kaggle_to_duckdb `
  --dataset-dir data\source\sephora_kaggle `
  --database-path $isolated `
  --catalog-only
```

Catalog-only mode records `ingestion_mode=catalog_only` and
`complete_product_and_review_ingestion=false`, and drops any previous
`raw.sephora_reviews` relation in that isolated target to prevent stale reviews
from appearing current.

Product inputs require `product_id`, `product_name`, `brand_name`,
`primary_category`, `ingredients`, `price_usd`, `rating`, and `reviews`.
Each review file requires `product_id`, `author_id`, `rating`,
`is_recommended`, `submission_time`, `review_text`, and `review_title`; review
files must have matching headers and column order. Product IDs must be
non-empty and unique; duplicates abort before source replacement. Review
product IDs must be non-empty. Duplicate review rows and orphan product
references are counted, retained, and reported. DuckDB parses CSVs directly
into bounded-memory staging tables; source relations retain source columns as
text and reviews carry `source_filename`. Invalid non-empty numeric product
values become NULL only in the canonical adapter and are counted in the
manifest. Changed inputs, parse failures, or mismatched download manifests abort
the transaction. Existing isolated targets receive a checksum-verified backup
before replacement; this safeguard does not authorize production promotion.

## Raw tables and canonical mapping

| Relation | Row grain and purpose |
| --- | --- |
| `raw.sephora_product_info` | One source product row; all source columns retained as text. |
| `raw.sephora_reviews` | One source review row; all source columns plus `source_filename`. |
| `raw.sephora_ingestion_manifest` | One row per loaded file, with download/ingestion times, source path, checksums, actual row counts, inventory, and validation summary. |
| `raw.raw_products` | Canonical product adapter consumed by the existing dbt product pipeline. |

`raw.sephora_reviews` retains every CSV field as text at one-row-per-review
grain. `product_id` is the source relationship key; `rating` is an individual
review rating, while `product_info.csv.rating` is a product-level aggregate.
`is_recommended`, feedback counts, submission time, review text/title, and
reviewer attributes remain source values. Review rows include `source_filename`
provenance and are never joined into product-grain models. The downloaded
review CSVs have an empty first header cell; DuckDB names that preserved column
`column00`. It is not treated as a review identifier.

The adapter maps the verified Kaggle headers to the existing product grain as follows:

| Kaggle product field | Canonical / Silver field | Meaning |
| --- | --- | --- |
| `product_id` | `raw.raw_products.id`, `product_id` | Stable source identifier; never generated. |
| `brand_name` | `brand`, `brand_standardized`, `brand_key` | Source brand and normalized grouping key. |
| `product_name` | `name`, `product_name`, `product_name_key` | Source name and normalized key. |
| `primary_category` | `category`, `source_category`, `primary_category` | Open category value normalized only for case/outer whitespace in Silver. |
| `secondary_category`, `tertiary_category` | Same-named columns | Source hierarchy retained independently. |
| `ingredients` | `ingredients`, `ingredients_raw`, `ingredients_text` | Source text retained; no JSON or delimiter assumptions are made. |
| `price_usd` | `price_usd` | Listed product price, not transaction price or revenue. |
| `rating` | `product_rating` | Product-level aggregate, distinct from each review's rating. |
| `reviews` | `aggregate_review_count` | Product-level aggregate, not the number of loaded review rows. |
| `loves_count` | `loves_count` | Popularity signal, not sales. |
| Product flags | Same-named optional columns | Preserved and typed where available; absent optional fields remain NULL. |

The old Beauty API's `origin` and five formulation booleans are not invented
for the Kaggle source. Review rows remain in their own raw relation and are
never joined into the product-grain model. Review-key, duplicate-row, orphan,
rating-parse, and recommendation-parse counts are recorded by ingestion; no
sales metrics are inferred from review or product catalogue data. Review
analytics are modeled separately at review grain below.

## dbt models and deterministic API

`stg_raw_products` is the Bronze product adapter. `int_product_catalog` is
Silver at one row per product source record; it preserves the category
hierarchy, trims/normalizes display and grouping fields, casts numeric fields,
and flags missing or malformed product attributes. Duplicate IDs and
brand/name candidates are diagnostics, not instructions to drop rows.
Ingredient diagnostics are limited to missing text until actual downloaded
examples justify a parser.

Gold includes:

- `mart_product_catalog`: product-grain detail with listed price, product-level
  rating, aggregate review count, hierarchy, and quality flags.
- `mart_catalog_by_category`: row counts and shares by open-ended normalized
  primary category.
- `mart_catalog_by_brand`: row counts and shares by normalized brand key.
- `mart_catalog_quality_summary`: product-row quality counts and rates, using
  all product source rows as the denominator.

No transaction, realized price, cost, margin, inventory movement, or customer
purchase data is available. Product aggregates `rating`, `reviews`, and
`loves_count` are not review-row counts, sales, or revenue.

The FastAPI catalog endpoints are `/health`, `/metrics/catalog`,
`/metrics/catalog/categories`, `/metrics/catalog/category-summary`,
`/metrics/catalog/brands`, and `/metrics/catalog/quality`. The API reads the
path in `RETAIL_ENGINE_DB_PATH` or defaults to `data\retail_engine.duckdb`.
Required missing/incompatible Gold relations return HTTP 503 rather than
success-shaped zero metrics. Existing API response keys tied only to the old
Beauty API (`origin`, formulation flags, and JSON ingredient structure) remain
present as null when they are not applicable to this source. The legacy
`missing_ingredient_payload_*` compatibility fields mirror ingredient-text
missingness; new source-specific fields report numeric and ingredient-text
diagnostics.

### Optional Groq assistant

`POST /assistant/ask` accepts a question and an optional `max_results` from 1
to 20:

```json
{
  "question": "Summarize the review ratings",
  "max_results": 10
}
```

The assistant currently supports allowlisted catalogue summary, category and
brand counts, catalogue quality, review summary, rating distribution,
recommendations, monthly trends, and review product/brand/category/quality
summaries. The operation is selected from the supported question patterns and
the corresponding result is calculated by the deterministic analytics layer.
The Groq call is constrained to the selected allowlisted operation; it cannot
run arbitrary SQL or provide unsupported sales, revenue, margin, inventory, or
customer metrics. Responses include the operation, source mart, metric
definition, and structured result. Unsupported questions are identified as
unsupported rather than answered with invented metrics.

The endpoint returns HTTP 503 when `GROQ_API_KEY` is missing or assistant
configuration is invalid. Provider failures after deterministic calculation
return the deterministic result with a non-`ok` `provider_status`; this does
not mean the live provider was verified. Offline tests mock provider calls and
do not require or verify a real Groq API key.

### Review-grain analytics

Review analytics use individual rows in `raw.sephora_reviews`; these counts and
ratings are not interchangeable with product-level `rating` or `reviews`
aggregates in the catalogue. `stg_raw_reviews` parses only audited source
formats and adds explicit missing/invalid flags. `int_review_analytics` keeps
review grain, left joins the unique product Gold mart, and retains missing or
orphan product references rather than multiplying or dropping rows. Reviewer
IDs, profile attributes, review text, and titles are not included in review
analytics API responses.

The review Gold marts and routes are:

| Mart | Route | Grain and denominator |
| --- | --- | --- |
| `mart_review_summary` | `/metrics/reviews` | Singleton over loaded review rows. Average and median rating use ratings from 1 through 5. Recommendation rate divides positive recommendations by rows with valid true/false values. |
| `mart_review_rating_distribution` | `/metrics/reviews/ratings` | One row per valid 1-to-5 rating; each share divides by all valid ratings. |
| `mart_review_recommendation_summary` | `/metrics/reviews/recommendations` | Singleton; missing and malformed recommendation values are separate from the valid recommendation denominator. |
| `mart_review_monthly_trends` | `/metrics/reviews/trends` | One row per parsed submission month. Review counts use all dated rows; average-rating and recommendation denominators are reported separately. |
| `mart_review_product_summary` | `/metrics/reviews/products` | Every product with one or more loaded review rows, including a missing-ID bucket if present. Sorted by review count descending, then product ID and name; no minimum-review cutoff. |
| `mart_review_brand_summary` | `/metrics/reviews/brands` | One row per normalized product brand, including the null-brand bucket. |
| `mart_review_category_summary` | `/metrics/reviews/categories` | One row per normalized primary category, including the null-category bucket. |
| `mart_review_quality_summary` | `/metrics/reviews/quality` | Singleton; each issue rate uses all loaded review rows as the denominator. |

Brand, category, and product review counts include every loaded row once.
Average ratings exclude missing, malformed, or out-of-range ratings; rates
include their valid-row denominator in the response. Recommendation values
accept numeric zero/one or boolean text. Blank values are reported as missing;
non-empty unparseable values are reported as invalid. Duplicate review
candidates are rows sharing product, author, rating, recommendation, date,
text, and title; this is a diagnostic candidate, not proof of duplication, and
no rows are removed. `column00` is a blank-header source field whose values
repeat across review files, so it is not treated as a globally unique review
identifier.

The feedback fields were audited before use. The three integer feedback counts
are populated for all loaded reviews, non-negative, and satisfy
`total_feedback_count = total_pos_feedback_count + total_neg_feedback_count`.
For the 532,819 rows with at least one vote, the source `helpfulness` ratio
matches positive votes divided by total votes within `0.000001`; the remaining
561,592 rows have no votes and a null ratio. The API therefore exposes:

- `helpfulness_review_rows`: review rows with feedback votes.
- `total_feedback_votes`, `positive_feedback_votes`, and
  `negative_feedback_votes`: sums over rows with valid, internally consistent
  feedback counts.
- `average_helpfulness`: unweighted mean of valid per-review ratios over
  feedback-bearing rows.
- `weighted_helpfulness_rate`: total positive votes divided by total feedback
  votes; null when the denominator is zero.
- Separate missing/inconsistent helpfulness and invalid feedback-count
  diagnostics.

The overall response also includes `median_rating` over `valid_rating_rows`;
both mean and median are null when no valid ratings exist. Example response
fields (counts abbreviated):

```json
{
  "total_review_rows": 1094411,
  "valid_rating_rows": 1094411,
  "average_rating": 4.299158,
  "median_rating": 5.0,
  "recommendation_rate": 0.839962,
  "valid_recommendation_rows": 926423,
  "helpfulness_review_rows": 532819,
  "total_feedback_votes": 4571493,
  "positive_feedback_votes": 3592138,
  "negative_feedback_votes": 979355,
  "average_helpfulness": 0.767782,
  "weighted_helpfulness_rate": 0.785769
}
```

To serve from a local isolated copy, set the database override only in the
server process environment and bind to loopback:

```powershell
$env:RETAIL_ENGINE_DB_PATH = $isolated
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The new review endpoints require the corresponding review Gold marts and
return HTTP 503 when they are absent or incompatible. Existing catalogue
endpoints remain independently available. Review aggregates are descriptive
of the loaded dataset snapshot; they do not imply sentiment, sales, purchases,
or a product's lifetime review history.

For isolated validation, configure dbt with the exact same working-copy path.
Put the profile, dbt target directory, and dbt logs outside the repository so
the configured production profile and generated files cannot be selected
accidentally:

```powershell
$profileDir = Join-Path $env:TEMP 'sephora-validation-profile'
New-Item -ItemType Directory -Force $profileDir | Out-Null
@"
sme_retail_analytics_engine:
  target: isolated
  outputs:
    isolated:
      type: duckdb
      path: '$isolated'
      schema: main
      threads: 4
"@ | Set-Content (Join-Path $profileDir 'profiles.yml')
$targetDir = Join-Path $env:TEMP 'sephora-dbt-target'
$logDir = Join-Path $env:TEMP 'sephora-dbt-logs'
dbt debug --project-dir dbt_retail --profiles-dir $profileDir `
  --log-path $logDir --target isolated
dbt parse --project-dir dbt_retail --profiles-dir $profileDir `
  --target-path $targetDir --log-path $logDir --no-partial-parse
dbt compile --project-dir dbt_retail --profiles-dir $profileDir `
  --target-path $targetDir --log-path $logDir --no-partial-parse
dbt build --project-dir dbt_retail --profiles-dir $profileDir `
  --target-path $targetDir --log-path $logDir --no-partial-parse
$env:RETAIL_ENGINE_DB_PATH = $isolated
python -c "import os; from fastapi.testclient import TestClient; from app.main import app; c=TestClient(app); print([(p, c.get(p).status_code) for p in ['/health', '/metrics/catalog', '/metrics/catalog/categories', '/metrics/catalog/category-summary', '/metrics/catalog/brands', '/metrics/catalog/quality']])"
```

Do not use the repository's default dbt profile for a migration validation: it
points to the configured warehouse. Confirm the selected profile/database path
before running dbt, and keep the API pointed at the same isolated file. The
API smoke check above uses in-process TestClient and does not start a listener.
The review models can be built without selecting unrelated models:

```powershell
dbt build --project-dir dbt_retail --profiles-dir $profileDir `
  --target isolated --target-path $targetDir --log-path $logDir `
  --no-partial-parse --select stg_raw_reviews int_review_analytics `
  mart_review_summary mart_review_rating_distribution `
  mart_review_recommendation_summary mart_review_monthly_trends `
  mart_review_product_summary mart_review_brand_summary `
  mart_review_category_summary mart_review_quality_summary
```

## Tests and benchmark

Run the offline ingestion and catalog tests, or the full suite:

```powershell
python -m pytest `
  tests\test_kaggle_downloader.py tests\test_sephora_ingestion.py `
  tests\test_catalog_metrics.py tests\test_review_metrics.py -q
python -m pytest tests -q
```

`tests\fixtures\sephora\` contains small synthetic CSV files for deterministic
offline tests; they are not a downloaded Kaggle snapshot and their row counts
must not be reported as real dataset observations.

To benchmark catalog routes locally:

```powershell
python scripts\benchmark_api.py --iterations 200
```

The benchmark uses in-process TestClient and reports p50/p95/mean latency; it
excludes external network latency and is not a test pass/fail gate.

An additional full-data live HTTP smoke test against the isolated 1,094,411-row
copy used Uvicorn on `127.0.0.1:8765`. Across 20 repeated local requests after
the first request, `/metrics/catalog`, `/metrics/reviews`, and
`/metrics/reviews/products` had warm medians of 15.43, 15.53, and 15.67 ms;
warm p95 values were 27.61, 16.61, and 43.60 ms. First requests measured
50.32–68.44 ms. These small samples include loopback HTTP overhead, exclude
external network latency, and are not an SLO benchmark; the `<10 ms` target
was not met in this full-data live HTTP sample.

## Download and isolated validation results

KaggleHub downloaded and validated dataset
`nadyinky/sephora-products-and-skincare-reviews` on 2026-10-20. The actual
local directory is `data\source\sephora_kaggle\`; the audit inventory and SHA-256
hashes are in its ignored `download_manifest.json`. All six CSVs decode as
UTF-8. `product_info.csv` has 26 source columns. Each review file has 19 source
columns; the first review header is blank in the source and DuckDB names that
preserved field `column00`. Review recommendation values include `0.0` and
`1.0`; validation accepts numeric zero/one and conventional boolean strings,
and rejects other numeric values.

| Downloaded file | Actual rows | Bytes |
| --- | ---: | ---: |
| `product_info.csv` | 8,494 | 7,912,721 |
| `reviews_0-250.csv` | 602,130 | 282,260,770 |
| `reviews_1250-end.csv` | 49,977 | 24,193,736 |
| `reviews_250-500.csv` | 206,725 | 100,294,822 |
| `reviews_500-750.csv` | 116,262 | 56,306,953 |
| `reviews_750-1250.csv` | 119,317 | 57,980,731 |

Full ingestion loaded 8,494 product rows and 1,094,411 review rows into a fresh
copy of production stored outside the repository. All 8,494 product IDs are
unique and non-null. No exact duplicate review rows, orphan review product
references, invalid review ratings, or invalid recommendation values were
found. Product quality included 83 repeated normalized brand/name candidates,
945 missing ingredient-text rows, 278 missing product ratings, and 278 missing
product-level aggregate review counts; source rows were retained. These
aggregates are descriptive catalogue/review diagnostics, not transactions,
sales, revenue, or purchases.

The full Python suite passed **87 tests** (one existing Starlette/httpx
TestClient deprecation warning). This cutover validation used
`C:\Users\eddyj\AppData\Local\anaconda3\python.exe` (Python 3.13.9);
`python` was not on the process PATH. dbt 1.12.5 and dbt-duckdb 1.11.0 used
that same environment. Isolated dbt `debug`, `parse`, `compile`, and `build`
passed. The build finished **PASS=61, WARN=0, ERROR=0, SKIP=0** (6 models and
55 data tests), with its database, profile, target, and logs kept outside the
repository.

All six FastAPI routes returned HTTP 200 against the built isolated warehouse.
Independent DuckDB SQL against the source-faithful raw product table matched
all 9 category groups, all 304 brand groups, and every field in the Gold
quality summary. Product/raw/mart counts were 8,494; review raw count was
1,094,411 across five files; the SQL orphan count was zero. The raw product
catalogue remained at product grain and was not inflated by review rows.

At this checkpoint, before the separately approved cutover, production was
unchanged at 37,236,736 bytes, UTC modification time
`2026-10-14T11:36:05.9287356Z`, and SHA-256
`5A9BEF0D623E6744FA388B22150ABD8299FF18C14104FE6316A8BC1201E14488`. The
later production cutover and its post-promotion verification are recorded
below.

The new readiness preflight rechecked the manifest against all current Kaggle
file sizes and hashes, read the production schema/counts through a read-only
DuckDB connection, and created a new isolated clone with an identical initial
fingerprint. No production ingestion or dbt command was run. An initial
isolated dbt run exposed that the project source uses DuckDB catalog name
`retail_engine`; naming the external candidate `retail_engine.duckdb` and
pointing the isolated profile at it resolved the alias mismatch. The final
build and all SQL/API verification below used that corrected external
candidate and reported no dbt warnings or errors.

### Historical production cutover preflight (2026-10-20)

The current production warehouse is
`C:\Users\eddyj\Documents\Data_Science\Projects\SME-Retail-Analytics-Engine\data\retail_engine.duckdb`.
Read-only inspection found `raw.raw_products` at 1,020 rows with 12 columns:
`id`, `brand`, `name`, `image_url`, `category`, `origin`,
`contains_fragrance`, `contains_drying_alcohol`, `contains_parabens`,
`contains_sulfates`, `contains_silicones`, and `ingredients`. The existing
`main.stg_raw_products` view and `main.mart_product_catalog` table also each
have 1,020 rows. The production fingerprint is 37,236,736 bytes,
`2026-10-14T11:36:05.9287356Z`, SHA-256
`5A9BEF0D623E6744FA388B22150ABD8299FF18C14104FE6316A8BC1201E14488`.
An older file `data\backups\retail_engine_20261014T112829473116Z.duckdb`
(24,915,968 bytes) already exists. It was not created or verified during this
preflight and is not accepted as a cutover restore point; create and verify a
new uniquely named backup if a future cutover is approved.

The checked-in dbt profile's active target is `dev`, pointing to
`data/retail_engine.duckdb`. FastAPI uses that same default path;
`RETAIL_ENGINE_DB_PATH` was unset and `.env` had no database override during
preflight. No Python, dbt, or API process was visible. Repeat all checks during
the actual maintenance window; do not rely on this earlier observation.

The local Kaggle output still exists. All six files' byte sizes and SHA-256
hashes match `data\source\sephora_kaggle\download_manifest.json`; no refresh or
large download is required. The isolated candidate began as an exact
37,236,736-byte, hash-matched copy, and was built at
`%TEMP%\sme-retail-kaggle-cutover-20261020\retail_engine.duckdb`, outside the
repository. After the latest isolated dbt rebuild, the final candidate is
461,647,872 bytes with SHA-256
`F14B3793FEE9CE89C1D6A06C534F93AF954B926833CA71DB19F8517AF5C66882`.
Keep the basename `retail_engine.duckdb`: the dbt source config uses
database/catalog name `retail_engine`. All isolated commands used an external
profile, target directory, and log directory.

This fresh isolated run loaded 8,494 source products and 1,094,411 source
reviews. It retained 8,494 rows in both `raw.sephora_product_info` and the
canonical `raw.raw_products`; `raw.sephora_reviews` contains 1,094,411
individual review rows with `source_filename`; the manifest has six file rows.
The product mart remains 8,494 rows with 8,494 distinct IDs, so review rows
did not inflate product grain. Orphan and exact duplicate review counts were
zero. Product diagnostics independently matched: 83 duplicate normalized
brand/name candidates, 945 missing ingredient-text rows, 278 missing
product-level ratings, 278 missing product aggregate review counts, and 1,227
rows with at least one quality issue. No invalid product numeric values,
invalid review ratings, or invalid recommendation values were found.

Independent SQL over source-faithful product input matched all 9 category
groups, 304 brand groups, and every count/rate in the Gold quality summary.
The final full test suite passed **87 tests** (one existing deprecation
warning). dbt debug, parse, compile, and build passed:
**PASS=61, WARN=0, ERROR=0, SKIP=0**. All six API routes returned HTTP 200
against the candidate. The production fingerprint remained unchanged after
validation. These results validate only the isolated candidate, not production
activation.

### Backup-first file promotion and rollback runbook

The selected cutover method is a file-level promotion of the fully ingested,
dbt-built, API-tested isolated candidate. The Kaggle loader rejects the
configured production path, so ingestion must remain isolated. For the
approved 2026-10-20 cutover, dbt was explicitly run against the promoted
production file with an external profile, target, and log directory to rebuild
downstream analytics. Any future production promotion or production-targeted
dbt run still requires separate explicit approval and a maintenance window;
the checked-in default profile must not be used for that operation.

The verified Windows environment used these executables; select the
corresponding project environment on other machines:

```powershell
$python = 'C:\Users\eddyj\AppData\Local\anaconda3\python.exe'
$dbt = 'C:\Users\eddyj\AppData\Local\anaconda3\Scripts\dbt.exe'
```

Expected database effects of promoting the candidate: replace the canonical
`raw.raw_products` product source; add/replace `raw.sephora_product_info`,
`raw.sephora_reviews`, and `raw.sephora_ingestion_manifest`; and ship the
matching dbt-built staging, intermediate, and Gold relations. The loader
replaces the three Kaggle raw relations and canonical product adapter in one
transaction; dbt rebuilds downstream analytics separately. Existing product
grain is preserved, and review rows remain separate. The main risks are
serving incompatible old code with the new schema, an interrupted file swap,
or promoting a candidate after its inputs/code have changed.

1. Confirm the approved code and candidate are the exact versions tested
   together. Stop the API and all jobs/processes that might hold the production
   DuckDB open. Reconfirm the production path resolves exactly to
   `data\retail_engine.duckdb`, record size/time/SHA-256, and stop if any
   process or open-file concern remains. For a basic process check:

   ```powershell
   $production = (Resolve-Path data\retail_engine.duckdb).Path
   $expectedProduction = Join-Path (Resolve-Path data).Path 'retail_engine.duckdb'
   if ($production -ne $expectedProduction) { throw "Unexpected production path: $production" }
   $active = Get-Process -ErrorAction SilentlyContinue |
     Where-Object { $_.ProcessName -match 'python|uvicorn|dbt' }
   if ($active) { $active | Select-Object ProcessName,Id; throw 'Stop warehouse users first.' }
   ```

   This process-name check is not a substitute for stopping the configured
   service and confirming its DuckDB handle is closed.
2. Use a unique external work directory and a fresh production copy. The
   following PowerShell outline guards path separation and verifies the source
   copy before ingestion:

   ```powershell
   $production = (Resolve-Path data\retail_engine.duckdb).Path
   $dataset = (Resolve-Path data\source\sephora_kaggle).Path
   $work = Join-Path $env:TEMP ('sme-retail-kaggle-cutover-' + (Get-Date -Format 'yyyyMMddTHHmmss'))
   if (Test-Path -LiteralPath $work) { throw "Work path already exists: $work" }
   New-Item -ItemType Directory -Path $work | Out-Null
   $candidate = Join-Path $work 'retail_engine.duckdb'
   Copy-Item -LiteralPath $production -Destination $candidate
   if ((Get-FileHash $production -Algorithm SHA256).Hash -ne
       (Get-FileHash $candidate -Algorithm SHA256).Hash) {
       throw 'Initial candidate fingerprint does not match production.'
   }
   if ((Resolve-Path $candidate).Path -eq $production) {
       throw 'Refusing to use the production database as the candidate.'
   }
   & $python -m src.ingestion.load_sephora_kaggle_to_duckdb `
     --dataset-dir $dataset --database-path $candidate
   ```

3. Put the profile, dbt target, and logs under `$work`; verify the profile
   `path` equals `$candidate` before invoking dbt:

   ```powershell
   $profileDir = Join-Path $work 'profile'
   $targetDir = Join-Path $work 'dbt-target'
   $logDir = Join-Path $work 'dbt-logs'
   New-Item -ItemType Directory -Force -Path $profileDir,$targetDir,$logDir | Out-Null
   @"
   sme_retail_analytics_engine:
     target: isolated
     outputs:
       isolated:
         type: duckdb
         path: '$candidate'
         schema: main
         threads: 4
   "@ | Set-Content (Join-Path $profileDir 'profiles.yml') -Encoding utf8
   if (-not ((Get-Content (Join-Path $profileDir 'profiles.yml') -Raw).Contains($candidate))) {
     throw 'dbt profile does not point at the isolated candidate.'
   }
   & $dbt debug --project-dir dbt_retail --profiles-dir $profileDir `
     --log-path $logDir --target isolated
   & $dbt parse --project-dir dbt_retail --profiles-dir $profileDir `
     --target-path $targetDir --log-path $logDir --no-partial-parse
   & $dbt compile --project-dir dbt_retail --profiles-dir $profileDir `
     --target-path $targetDir --log-path $logDir --no-partial-parse
   & $dbt build --project-dir dbt_retail --profiles-dir $profileDir `
     --target-path $targetDir --log-path $logDir --no-partial-parse
   ```

   Check each exit code and each resolved dbt connection path; do not use the
   repository `dev` profile. The candidate filename must stay
   `retail_engine.duckdb` so the configured dbt source catalog name resolves.
   Run the full offline suite with `& $python -m pytest tests -q`. Point API
   smoke tests at the candidate only by setting `RETAIL_ENGINE_DB_PATH` in
   their process; check `/health`, `/metrics/catalog`,
   `/metrics/catalog/categories`, `/metrics/catalog/category-summary`,
   `/metrics/catalog/brands`, and `/metrics/catalog/quality`. Confirm source
   row counts, separate grains, review orphans/duplicates, category/brand
   groups, and all quality summary fields with independent SQL.

4. Before promotion, review the manifests, validation report, candidate
   fingerprint, and explicit approval. During the approved maintenance window,
   record a fresh production fingerprint and create a unique verified backup:

   ```powershell
   $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
   $backupDir = Join-Path (Split-Path $production) 'backups'
   New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
   $backup = Join-Path $backupDir "retail_engine_pre_kaggle_$stamp.duckdb"
   Copy-Item -LiteralPath $production -Destination $backup
   if ((Get-FileHash $production -Algorithm SHA256).Hash -ne
       (Get-FileHash $backup -Algorithm SHA256).Hash) {
       throw 'Backup checksum mismatch; do not promote.'
   }
   & $python -c "import duckdb,sys; c=duckdb.connect(sys.argv[1],read_only=True); print(c.execute('select count(*) from raw.raw_products').fetchone()[0]); c.close()" $backup
   if ($LASTEXITCODE -ne 0) { throw 'Backup did not pass read-only DuckDB verification.' }
   ```

   Stage and hash-check the exact candidate before moving the production file.
   Run this only after separate approval and with all warehouse users stopped:

   ```powershell
   $promotionStage = Join-Path (Split-Path $production) "retail_engine_kaggle_stage_$stamp.duckdb"
   $previousLive = Join-Path $backupDir "retail_engine_previous_live_$stamp.duckdb"
   $failedFile = Join-Path $backupDir "retail_engine_failed_promotion_$stamp.duckdb"
   if ((Test-Path $promotionStage) -or (Test-Path $previousLive) -or (Test-Path $failedFile)) {
     throw 'A promotion artifact path already exists.'
   }
   Copy-Item -LiteralPath $candidate -Destination $promotionStage
   if ((Get-FileHash $candidate -Algorithm SHA256).Hash -ne
       (Get-FileHash $promotionStage -Algorithm SHA256).Hash) {
     throw 'Staged candidate hash mismatch.'
   }
   Move-Item -LiteralPath $production -Destination $previousLive
   try {
     Move-Item -LiteralPath $promotionStage -Destination $production
     if ((Get-FileHash $candidate -Algorithm SHA256).Hash -ne
         (Get-FileHash $production -Algorithm SHA256).Hash) {
       throw 'Promoted database hash differs from the validated candidate.'
     }
   } catch {
     if (Test-Path -LiteralPath $production) {
       Move-Item -LiteralPath $production -Destination $failedFile
     }
     Copy-Item -LiteralPath $backup -Destination $production
     if ((Get-FileHash $backup -Algorithm SHA256).Hash -ne
         (Get-FileHash $production -Algorithm SHA256).Hash) {
       throw 'Automatic rollback copy failed; keep services stopped.'
     }
     throw
   }
   ```

   Keep both the checksum-verified backup and the moved original until the
   rollback window closes. Never run the Kaggle ingestion CLI against
   production. A production-targeted dbt build is a separate, explicitly
   approved operation and must use a verified external profile and isolated
   target/log paths.

5. After promotion, verify the expected schemas and row counts:
   `raw.sephora_product_info` = 8,494 products;
   `raw.sephora_reviews` = 1,094,411 review rows;
   `raw.sephora_ingestion_manifest` = six file rows;
   `raw.raw_products` and `main.mart_product_catalog` = 8,494 product rows;
   category and brand marts = 9 and 304 rows. Recheck the quality summary
   against independent SQL, confirm the six API routes and response schemas,
   and record the promoted fingerprint and API version. Use a read-only DuckDB
   connection for the database checks and the configured deployment base URL
   (do not guess a listener address) for HTTP checks:

   ```powershell
   $verify = @'
   import duckdb, sys
   connection = duckdb.connect(sys.argv[1], read_only=True)
   try:
       actual = connection.execute("""
           SELECT
               (SELECT COUNT(*) FROM raw.sephora_product_info),
               (SELECT COUNT(*) FROM raw.sephora_reviews),
               (SELECT COUNT(*) FROM raw.sephora_ingestion_manifest),
               (SELECT COUNT(*) FROM raw.raw_products),
               (SELECT COUNT(*) FROM main.mart_product_catalog),
               (SELECT COUNT(*) FROM main.mart_catalog_by_category),
               (SELECT COUNT(*) FROM main.mart_catalog_by_brand)
       """).fetchone()
       expected = (8494, 1094411, 6, 8494, 8494, 9, 304)
       product_columns = {row[0] for row in connection.execute(
           "DESCRIBE raw.sephora_product_info"
       ).fetchall()}
       review_columns = {row[0] for row in connection.execute(
           "DESCRIBE raw.sephora_reviews"
       ).fetchall()}
       assert actual == expected, (actual, expected)
       assert {"rating", "reviews"} <= product_columns
       assert {"rating", "source_filename"} <= review_columns
       assert "reviews" not in review_columns
       print("verified counts:", actual)
   finally:
       connection.close()
   '@
   & $python -c $verify $production
   if ($LASTEXITCODE -ne 0) { throw 'Post-cutover DuckDB verification failed.' }
   $apiBaseUrl = '<configured deployment base URL>'
   $routes = @('/health','/metrics/catalog','/metrics/catalog/categories','/metrics/catalog/category-summary','/metrics/catalog/brands','/metrics/catalog/quality')
   foreach ($route in $routes) {
     $response = Invoke-WebRequest -Uri ($apiBaseUrl.TrimEnd('/') + $route)
     if ($response.StatusCode -ne 200) { throw "API check failed: $route" }
   }
   ```

If any step fails, stop the API and all DuckDB users. Preserve the failed
candidate separately, restore the verified pre-cutover backup to
`data\retail_engine.duckdb`, and verify its original SHA-256, size, and
read-only open/query before restarting the previous API version. Keep the
backup, candidate, and failure copy until the rollback window closes. File
replacement is not a DuckDB transaction and is never authorized by successful
isolated validation or approval of this documentation task.

For a post-promotion failure, the explicit rollback sequence is:

```powershell
$failedPath = Join-Path $backupDir "retail_engine_failed_$stamp.duckdb"
if (Test-Path -LiteralPath $production) {
  Move-Item -LiteralPath $production -Destination $failedPath
}
Copy-Item -LiteralPath $backup -Destination $production
if ((Get-FileHash $backup -Algorithm SHA256).Hash -ne
    (Get-FileHash $production -Algorithm SHA256).Hash) {
  throw 'Restored production hash mismatch; keep services stopped.'
}
& $python -c "import duckdb,sys; c=duckdb.connect(sys.argv[1],read_only=True); print(c.execute('select count(*) from raw.raw_products').fetchone()[0]); c.close()" $production
if ($LASTEXITCODE -ne 0) { throw 'Restored database failed read-only verification.' }
```

Restart the previous API version only after this restore check succeeds.

### Production cutover execution (2026-10-20)

The cutover was explicitly approved and executed after the isolated
candidate, dataset manifest, and maintenance checks were revalidated. No
download refresh occurred. The source CSV sizes and SHA-256 hashes still
matched `data\source\sephora_kaggle\download_manifest.json`.

- **Production file:** `data\retail_engine.duckdb`.
- **Pre-cutover restore point:** `data\backups\retail_engine_pre_kaggle_20261020T112237872Z.duckdb`,
  37,236,736 bytes, SHA-256
  `5A9BEF0D623E6744FA388B22150ABD8299FF18C14104FE6316A8BC1201E14488`.
  Its relation/schema/column/type/row-count inventory matched the old live
  database. The previous live file was also preserved at
  `data\backups\retail_engine_previous_live_20261020T113241643Z.duckdb` with
  the same size and SHA-256. Keep both files until the rollback window closes.
- **Promotion:** the validated candidate
  `%TEMP%\sme-retail-kaggle-cutover-20261020\retail_engine.duckdb` was staged
  on the production volume, hash-checked, and promoted with
  `System.IO.File.Replace`. Its pre-dbt hash was
  `F14B3793FEE9CE89C1D6A06C534F93AF954B926833CA71DB19F8517AF5C66882`.
- **Post-promotion dbt:** `dbt debug`, `dbt parse`, `dbt compile`, and `dbt
  build` all passed against the exact production path using the external
  `%TEMP%\sme-retail-kaggle-cutover-20261020\production-profile\profiles.yml`,
  target `cutover`, and separate production dbt target/log directories. The
  build finished **PASS=61, WARN=0, ERROR=0, SKIP=0**. No Kaggle ingestion
  command was run against production.

The production profile was checked to contain the resolved production path
before these commands were run:

```powershell
$production = (Resolve-Path -LiteralPath 'data\retail_engine.duckdb').Path
$work = Join-Path $env:TEMP 'sme-retail-kaggle-cutover-20261020'
$profileDir = Join-Path $work 'production-profile'
$targetDir = Join-Path $work 'production-dbt-target'
$logDir = Join-Path $work 'production-dbt-logs'
$profilePath = Join-Path $profileDir 'profiles.yml'
if (-not ((Get-Content -LiteralPath $profilePath -Raw).Contains($production))) {
  throw 'dbt profile does not point at the resolved production file.'
}
& $dbt debug --project-dir dbt_retail --profiles-dir $profileDir `
  --log-path $logDir --target cutover
if ($LASTEXITCODE -ne 0) { throw 'Production dbt debug failed.' }
& $dbt parse --project-dir dbt_retail --profiles-dir $profileDir `
  --target-path $targetDir --log-path $logDir --target cutover --no-partial-parse
if ($LASTEXITCODE -ne 0) { throw 'Production dbt parse failed.' }
& $dbt compile --project-dir dbt_retail --profiles-dir $profileDir `
  --target-path $targetDir --log-path $logDir --target cutover --no-partial-parse
if ($LASTEXITCODE -ne 0) { throw 'Production dbt compile failed.' }
& $dbt build --project-dir dbt_retail --profiles-dir $profileDir `
  --target-path $targetDir --log-path $logDir --target cutover --no-partial-parse
if ($LASTEXITCODE -ne 0) { throw 'Production dbt build failed.' }
```

- **Production relations:** `raw.sephora_product_info` has 8,494 rows;
  `raw.sephora_reviews` has 1,094,411 review-grain rows across five files;
  `raw.sephora_ingestion_manifest` has six file rows; `raw.raw_products` and
  `main.mart_product_catalog` each have 8,494 product-grain rows;
  `main.mart_catalog_by_category` has 9 groups and
  `main.mart_catalog_by_brand` has 304 groups. Product IDs are unique.
  Independent SQL found zero orphan review references and zero exact
  duplicate review rows (excluding source filename). Category groups, brand
  counts/shares, and all 31 quality-summary fields matched independently
  calculated SQL from the raw product source. The quality summary reports
  1,227 products with at least one issue, including 83 duplicate
  brand/name candidates and 945 missing ingredient-text rows.
- **API verification:** all six routes (`/health`, `/metrics/catalog`,
  `/metrics/catalog/categories`, `/metrics/catalog/category-summary`,
  `/metrics/catalog/brands`, `/metrics/catalog/quality`) returned HTTP 200
  through FastAPI `TestClient` with `RETAIL_ENGINE_DB_PATH` explicitly set to
  the promoted production file. The expected product, category, brand, and
  quality response counts were checked. No API service was running during
  the preflight, so this verifies application behavior against production
  storage, not a deployed listener or external endpoint.
- **Current production fingerprint after dbt:** 427,044,864 bytes, UTC
  modification time `2026-10-20T11:43:42.5924098Z`, SHA-256
  `E36903CF6096890A059CDEBF7B0971821DA69FE165C3BAA3D979523F7D475079`.
  The production dbt build rewrote downstream relations after file
  promotion, so this final fingerprint is expected to differ from the
  isolated candidate's pre-promotion fingerprint. The pre-cutover backups
  remain unchanged.

**Rollback:** stop all application and warehouse users, preserve the current
production file as a uniquely named failed-cutover artifact, restore
`retail_engine_pre_kaggle_20261020T112237872Z.duckdb` to
`data\retail_engine.duckdb`, and verify the restored file's 37,236,736-byte
size, SHA-256
`5A9BEF0D623E6744FA388B22150ABD8299FF18C14104FE6316A8BC1201E14488`, and
read-only DuckDB queryability before restarting the prior application. The
exact PowerShell restore/check sequence is above. The backup and prior live
copy have not been removed.

### Legacy Beauty API loader

`src/ingestion/load_beauty_api_to_duckdb.py` is deprecated. Running it without
an explicit opt-in now exits before loading credentials, making a network
request, or opening DuckDB:

```powershell
& $python -m src.ingestion.load_beauty_api_to_duckdb
```

The legacy source can only be invoked with
`--allow-legacy-beauty-api`; do not use that flag for this pipeline. KaggleHub
is the only intended/default Sephora source. No transaction, revenue, margin,
inventory, purchase, or sales facts are derived from the Kaggle product or
review data.
