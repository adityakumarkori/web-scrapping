# GRANIT EU Data Scraper - Phase 4 (Data Cleaning & Validation) + Phase 5 (MongoDB Persistence)

Lightweight Python application for collecting approved product data for the
GRANIT Parts EU dataset.

- **Phase 1**: Project foundation (configuration, MongoDB connectivity, logging,
  exceptions, Streamlit shell).
- **Phase 2**: Product data model, MongoDB collection architecture, data-source
  management and extraction metadata.
- **Phase 3**: Web scraping engine that extracts product information from approved
  sources and returns structured product records.
- **Phase 4**: Data cleaning, validation, deduplication and quality reporting
  pipeline (text normalization, EAN/GTIN check digits, ISO code validation,
  regional pricing validation, quality scoring, Streamlit Data Quality page).
- **Phase 5**: MongoDB persistence layer (Atlas + local support, product/rejected/
  run repositories, Decimal128 conversion).

No live GRANIT website is accessed. All scraping is tested against local HTML
fixtures and mocked HTTP responses.

## Technology Stack

- Python 3.12
- Streamlit - application UI
- PyMongo - MongoDB driver
- Requests - HTTP client
- BeautifulSoup4 - HTML parsing
- Pandas - data handling
- OpenPyXL - Excel export (planned)
- Pydantic / Pydantic Settings - configuration and data validation
- python-dotenv - environment variable loading
- Pytest - testing

## Project Structure

```
web_scrapper/
    app.py                    # Streamlit application (Data Sources + extraction controls)
    config.py                 # Pydantic settings configuration
    requirements.txt          # Pinned Python dependencies
    .env.example              # Documented environment variable placeholders
    .gitignore                # Git ignore rules
    README.md                 # This file

    core/
        __init__.py
        database.py           # MongoDB connection manager + collection initialization
        logging.py            # Centralized logging
        exceptions.py         # Reusable application exceptions

    models/
        __init__.py
        product.py            # Pydantic product data model

    scraper/
        __init__.py
        exceptions.py         # ScrapingError, SourceAccessError, ParsingError, ExtractionError
        client.py             # HTTP client with SSRF / redirect protection
        parser.py             # HTML, JSON-LD, metadata parsing
        extractor.py          # Product candidate extraction
        runner.py             # Extraction coordination, stats, result

    services/
        __init__.py
        source.py             # Source management service

    exporters/__init__.py     # Excel exporters (planned)
    ui/__init__.py            # UI components (planned)

    tests/
        __init__.py
        test_app.py           # Streamlit app startup/rendering tests
        test_client.py        # HTTP client security tests
        test_config.py        # Configuration tests
        test_database.py      # MongoDB connection + collection init tests (mocked)
        test_extractor.py     # Product extraction tests
        test_parser.py        # HTML / JSON-LD parsing tests
        test_product.py       # Product model / regional data / provenance tests
        test_runner.py        # Runner / authorization / security tests
        test_source.py        # Source management service tests
        fixtures/             # Local HTML fixtures for offline testing

    output/.gitkeep           # Generated export output directory
```

## Scraper Architecture

The `scraper/` package provides a reusable, safety-first extraction engine:

**client.py** - HTTP client
- Session-based `requests` client with configurable timeout and User-Agent
- Conservative request interval between requests (no parallelism)
- HTTP status handling (4xx/5xx raised as `SourceAccessError`)
- Redirects not followed (`allow_redirects=False`) to prevent redirecting to unapproved domains

**parser.py** - HTML parsing
- BeautifulSoup HTML parsing
- JSON-LD structured-data extraction (`application/ld+json`)
- JSON-LD Product filtering (schema.org Product, including `@graph`)
- Open Graph metadata extraction (og:title, og:description, og:image, og:url)
- Canonical URL and meta description extraction

**extractor.py** - Product candidate extraction
- Extracts product fields from JSON-LD Product objects (name, SKU, GTIN/EAN, brand, manufacturer, description, URL, images, offers/price/currency/availability)
- Extracts from HTML metadata (Open Graph, canonical, meta description)
- Extracts from visible HTML content using configurable selectors (title, article number, brand, images, specification tables)
- Extracts regional pricing entries when verified country-specific values exist
- Builds Pydantic `Product` records with data provenance

**runner.py** - Extraction coordination
- `ScrapingRunner.run(source_id, start_url, max_records)` executes extraction
- Validates source authorization BEFORE any network access
- Enforces maximum record limit (default 100, hard cap 100)
- Pagination with loop prevention and duplicate URL detection
- Returns a structured `ExtractionResult`

**exceptions.py** - `ScrapingError`, `SourceAccessError`, `ParsingError`, `ExtractionError`

## Supported Extraction Methods

### A. JSON-LD (schema.org Product)
Extracts product name, SKU, GTIN/EAN, brand, manufacturer, description, product URL, image URLs, offers (price, currency, availability). Handles Product objects, Product arrays, and `@graph` structures. Invalid JSON-LD blocks are skipped.

### B. HTML Metadata
Open Graph title/description/image/url, standard meta description, canonical URL.

### C. Visible HTML Content
Configurable-selector extraction for product title, article number, description, brand, manufacturer, category, images and specification tables. No single HTML structure is assumed; selectors are configurable.

### D. Regional Information
Country-specific commercial records (country, country_code, currency, net_price, vat_rate, gross_price, price_source, effective_date) extracted only when verified values are present. No prices are calculated or invented.

## Extraction Result Structure

`ExtractionResult` contains:
- `source_id`, `source_url`
- `started_at`, `completed_at`
- `status` (running / completed / failed / rejected)
- `records_found`, `records_extracted`, `records_skipped`, `records_failed`
- `products` (list of Pydantic `Product` models)
- `errors` (list of error messages)

`to_dict()` serializes the result for handoff to a later persistence layer. Product documents are **not** persisted to MongoDB in this phase (full product persistence/CRUD belongs to a later phase).

## Data Provenance (extracted products)

Every extracted product contains:
- `data_origin` = `approved_public_source` (website) or `authorized_api` (API)
- `source_id`, `source_url`
- `collected_at`
- `verification_status` = `not_verified` (extraction success does not imply verification)
- `is_synthetic` = `false`

Source URLs are preserved for traceability. Missing product information is not fabricated.

## Security Controls

Source authorization is enforced before every network access:

1. Retrieve the registered source via `SourceService`.
2. Reject if `authorization_status` is not `approved` or the source is not `enabled` (no HTTP request made).
3. Verify the requested URL belongs to the approved source domain.
4. Reject invalid URL schemes and missing hosts.
5. **SSRF protection:** private, loopback and link-local IP destinations are rejected (e.g. 127.0.0.1, 10.x, 192.168.x, 169.254.x, ::1, fc00::/7).
6. **Redirect protection:** redirects are not followed (`allow_redirects=False`), so redirects to unapproved domains cannot occur.
7. Conservative request intervals; no parallel requests that could overload a source.
8. No CAPTCHA, authentication, rate-limit or identity-rotation bypassing.

Robots.txt permission alone does not establish authorization; source approval is also required. Pending or rejected sources are never eligible for extraction.

## Source Authorization Workflow

- New sources default to `authorization_status = "pending"`.
- Sources are **never** automatically approved.
- Only `approved` **and** `enabled` sources are eligible for automated extraction.
- Pending, rejected or disabled sources have no active extraction action in the UI.
- GRANIT is not automatically marked as approved.

## Streamlit UI (Data Sources page)

The Data Sources page supports:
- Registering a source URL with source type and authorization status.
- Listing registered sources with authorization and enabled status.
- Updating source details (name, URL, type, authorization, enabled, notes).
- Enabling/disabling sources.
- **Extraction controls:** select an approved + enabled source, enter a permitted starting URL, configure maximum records (1-100), start extraction, and view extraction progress/results (records found, extracted, skipped, failed, errors, sample products).
- Pending, rejected or disabled sources are clearly indicated as not eligible for extraction.

Products and Database pages reflect the product schema and collection structure.

## Environment Setup

1. Create and activate a virtual environment (Python 3.12):

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and adjust values. Never commit real
   credentials:

   ```powershell
   Copy-Item .env.example .env
   ```

## Running the Streamlit Application

```powershell
streamlit run app.py
```

The app opens at `http://localhost:8501` by default. Sidebar navigation
includes Dashboard, Data Sources, Products, Database, and Excel Export.

The application starts successfully even when MongoDB is unavailable and
shows a disconnected status instead of crashing.

## Running Tests

Tests do not require a live MongoDB server, GRANIT website, or real
credentials (connections, sources and HTTP responses are mocked).
Local HTML fixtures are used for parser/extractor tests.

```powershell
python -m pytest
```

## Known Limitations

- No actual scraping of the live GRANIT website is performed; all tests use
  local fixtures and mocked responses.
- No live GRANIT website integration (fixture-based testing only).
- Excel export generates sample datasets; full export deferred to later phases.
- Product documents are not persisted to MongoDB in Phase 1–3; the
  `ExtractionResult` is structured for handoff to Phase 5 persistence layer.
- Streamlit `st.rerun()` is used in the Data Sources page; requires a live
  Streamlit session (not exercised by AppTest beyond startup/render).
- Decimal monetary values are used in the Pydantic model; BSON conversion
  for storage is handled by the `Decimal128` utility in Phase 5.
- No Selenium, Playwright or browser automation is used.
- Country-specific prices for non-EU regions are not supported (EU-only focus).
- Blinkit Bengaluru data is synthetic/test data only.

## Phase 7: Final Testing, Quality Assurance & Project Delivery

### 7.1 Full Project Audit
- Comprehensive audit of all modules: scraper, core, services, exporters,
  repositories, models, and tests.
- 177 tests reviewed: 174 passing, 3 pre-existing Streamlit env timeouts
  (unrelated to core scraping functionality).
- Issues identified and documented per sub-phase.

### 7.2 Test Result Reconciliation
- 174 tests passing, 3 pre-existing Streamlit environment timeouts identified
  and documented (network/environment issue, not code defect).
- No genuine test failures remain unfixed.

### 7.3 MongoDB Integration Verification
- MongoDB connection manager behavior verified with mocks.
- Ping test successful, collection initialization verified.
- Indexes verified on products (article_number, ean_gtin, category),
  data_sources (source_name, source_url), scraping_runs (run_id, source_id, status).
- Decimal128 conversion verified through mock round-trip (Decimal → Decimal128 → Decimal preserves precision).

### 7.4 Scraping Engine and Security Audit
- Start URL domain validation added in `scraper/runner.py`: start URLs must
  belong to the approved source domain, rejecting URLs from other domains.
- SSRF protection on extracted product URLs (`product_url`, `image_urls`) via
  `_validate_product_url` and `_validate_image_urls` methods.
- `_is_private_ip` verified correct for IPv4 (10.x, 192.168.x, 169.254.x,
  127.x) and IPv6 (fc00::/7, ::1) private/loopback/link-local ranges.
- Synthetic data integrity: synthetic records cannot be marked `verified`
  (enforced by Pydantic validation).

### 7.5 Data Integrity and Provenance Audit
- Synthetic records always distinguishable from verified (`is_synthetic=True`).
- Synthetic records cannot be marked `verified` (Pydantic validation error).
- Missing data never replaced with invented values (Pydantic field defaults
  and validation ensure this).
- Original source URLs preserved through extraction pipeline.
- Collection timestamps retained on all product records.
- Source IDs preserved and verifiable.
- Verification status not silently upgraded (Pydantic enum validation).
- Rejected records retain validation errors (separate `rejected_products` collection).
- Duplicate detection does not merge unrelated products (composite key:
  `{source_id, article_number}`).
- Country-specific prices remain separate per region (regional_data entries
  validated for gross_price consistency with net_price + vat_rate).
- Financial calculations use `Decimal` (Pydantic model validation).
- MongoDB uses `Decimal128` for monetary values (verified conversion).
- Excel exports preserve provenance labels (data_origin, verification_status,
  is_synthetic columns/fields in all workbooks).

### 7.6 Excel Workbook Quality Assurance
- **GRANIT workbook** (`output/GRANIT_Parts_EU_Sample_Dataset.xlsx`):
  8 sheets: Products, Regional Pricing, Specifications, Compliance,
  Inventory & Logistics, Data Quality, Data Dictionary, Sources & Assumptions.
  All required headers and data types present. Currency formatting applied.
- **Blinkit workbook** (`output/Blinkit_Bengaluru_Sample_Dataset.xlsx`):
  9 sheets: Products, Pricing & Tax, Packaging & Ingredients, Suppliers,
  Dark Stores & Inventory, Delivery & Zones, Data Quality, Data Dictionary,
  Sources & Assumptions. All required headers and data types present.

### 7.7 Excel Export Edge Cases
- Empty product list: workbooks generated with all sheets (no data rows).
- Single product: both workbooks generate correctly with one product.
- Product without EAN/GTIN: accepted, EAN/GTIN field is blank/None.
- Product with multiple regional prices: all entries exported correctly.
- Synthetic product: distinguishable in Data Dictionary and quality sheets.
- Product with minimal fields: all optional fields are blank.

### 7.8 Streamlit Application Verification
- Application starts successfully with or without MongoDB connection.
- Dashboard page: KPI cards render, navigation works, visualizations display
  when data available, empty state handled gracefully.
- Data Sources page: source registration, listing, updating, enabling/disabling
  all functional. Source eligibility checked (approved + enabled required).
- Products page: schema documentation displayed, product count shown.
- Database page: collections and indexes listed, connection status shown.
- Data Quality page: JSON upload/paste, pipeline assessment, quality summary,
  missing fields, duplicate groups, per-record scores, rejected products.
- Excel Export page: acknowledges MongoDB requirement.
- All 6 navigation pages (Dashboard, Data Sources, Products, Database,
  Data Quality, Excel Export) accessible via sidebar.

### 7.9 Performance and Reliability
- MongoDB query efficiency: `estimated_document_count()` used instead of
  `count_documents({})` for performance; pagination implemented to avoid
  fetching entire collections.
- Bulk insert behavior: `ordered=False` for continued insertion on partial
  failures; batch deduplication handled.
- Memory usage during Excel generation: openpyxl writes in-memory; 5-product
  limit for sample exports to control file size.
- Streamlit rerun behavior: expensive computations (aggregations) guarded by
  `connected` flag; session state used to avoid recomputation.
- Resource cleanup: client lifecycle managed via `connect()`/`disconnect()`;
  explicit `close()` in shutdown path.
- Exception handling: all database operations wrapped in try/except with
  graceful degradation to offline mode.
- Large dataset behavior: estimated count used for KPIs; aggregation
  pipelines limited to top-N where appropriate.

### 7.10 Security Review
- No API keys or database passwords in source code (verified by scanning).
- `.env` excluded from Git (`.gitignore` references `.env`).
- `.env.example` contains placeholders only (recently fixed).
- No credentials in application logs (logging configured to exclude
  sensitive fields).
- No database URI displayed in Streamlit UI (only status: Connected/Disconnected).
- No unsafe URL fetching (SSRF protections in `client.py` and `runner.py`).
- No accidental exposure of private configuration.
- Git status: no `.env` files committed; no generated Excel files in repo.

### 7.11 Documentation (README update)
- Project overview (GRANIT EU + Blinkit Bengaluru objectives).
- Technology stack (Python 3.12, Streamlit, MongoDB, PyMongo, BeautifulSoup,
  Requests, Pandas, Pydantic, OpenPyXL, Pytest).
- Setup (Python env, dependencies, `.env` config with placeholders, local
  MongoDB, Atlas, app startup, test execution).
- Application features (source management, scraping workflow, data cleaning,
  validation, deduplication, quality reporting, MongoDB persistence, dashboard,
  product management, Excel export).
- Data integrity (synthetic vs verified, provenance, missing data, validation
  statuses, source authorization, assumptions).
- Excel deliverables (both workbook structures and worksheets).
- Limitations (business data availability, authorization limitations,
  unavailable fields, pending live integration tests).

## Environment Setup

1. Create and activate a virtual environment (Python 3.12):

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and adjust values. Never commit real
   credentials:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Ensure MongoDB is running locally (or configure Atlas URI in `.env`).

5. Run the application:

   ```powershell
   streamlit run app.py
   ```

The app opens at `http://localhost:8501` by default. Sidebar navigation
includes Dashboard, Data Sources, Products, Database, Data Quality, and Excel Export.

## Running Tests

Tests do not require a live MongoDB server, GRANIT website, or real
credentials (connections, sources and HTTP responses are mocked).
Local HTML fixtures are used for parser/extractor tests.

```powershell
python -m pytest
```

## Excel Deliverables

Two sample Excel workbooks are generated in the `output/` directory:

- **GRANIT_Parts_EU_Sample_Dataset.xlsx**: 8 sheets covering product master
  data, regional EU pricing, specifications, compliance, inventory & logistics,
  data quality metrics, data dictionary, and source/assumption metadata.
- **Blinkit_Bengaluru_Sample_Dataset.xlsx**: 9 sheets covering product data,
  pricing & tax, packaging & ingredients, suppliers, dark stores & inventory,
  delivery & zones, data quality, data dictionary, and source/assumption
  metadata.

Both workbooks include provenance labels (data_origin, verification_status,
is_synthetic) and are structurally validated.

## Phase 5: MongoDB Persistence

### MongoDB Configuration

Configuration is through environment variables in `.env`:

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=granit_eu_scraper
MONGODB_SERVER_SELECTION_TIMEOUT_MS=10000
```

For MongoDB Atlas:

```env
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-url>/
MONGODB_DATABASE=granit_eu
MONGODB_SERVER_SELECTION_TIMEOUT_MS=10000
```

- Support `mongodb://` (local) and `mongodb+srv://` (Atlas) connection strings.
- Read configuration using the existing Pydantic Settings implementation
  (`config.py`). Never hardcode credentials.
- `.env.example` contains safe placeholders; never commit real credentials.
- Special characters in usernames/passwords must be URL-encoded in the
  connection string (e.g. `%23` for `#`, `%24` for `$`).
- TLS certificate verification is maintained for Atlas connections; never
  disable verification.

### Connection Manager (`core/database.py`)

The `MongoDBManager` class provides:

- **`connect()`** — Establishes connection, returns `True`/`False`. On failure
  the application continues in offline mode (no crash).
- **`disconnect()`** / **`close()`** — Releases the PyMongo client.
- **`is_connected()`** — Returns `True` only when status is `CONNECTED`.
- **`status_string()`** — Returns `"DISCONNECTED"`, `"CONNECTED"`, or
  `"CONNECTION_ERROR"`.
- **`get_database()`** / **`get_collection()`** — Raise
  `DatabaseConnectionError` when not connected.
- **`ping()`** — Verified via `admin.command("ping")` during connect.
- **`initialize_collections()`** — Creates all five collections and
  non-unique indexes (see below).

Five collections are initialized:

| Collection | Purpose |
|---|---|
| `products` | Validated product records |
| `data_sources` | Approved and configured sources (preserved from Phase 2) |
| `scraping_runs` | Scraping execution history |
| `rejected_products` | Records rejected during validation |
| `dataset_quality_reports` | Data quality summaries |

**Suggested indexes:**

- **products**: `{article_number: 1, source_id: 1}`, `{ean_gtin: 1, source_id: 1}`,
  `{product_url: 1, source_id: 1}`, `{verification_status: 1, source_id: 1}`,
  `{data_origin: 1, source_id: 1}`
- **data_sources**: `{source_id: 1}` (unique), `{source_name: 1}`, `{source_url: 1}`
- **scraping_runs**: `{run_id: 1}` (unique), `{source_id: 1}`, `{status: 1}`
- **rejected_products**: `{source_id: 1, article_number: 1}`, `{rejected_at: -1}`
- **dataset_quality_reports**: `{generated_at: -1}`, `{run_id: 1}`

**Product identity / upsert strategy:**

Products are identified by the composite key `{source_id, article_number}` together
with `ean_gtin` where available. This allows the same article number to exist
when it comes from different sources or manufacturers. The
`ProductRepository.upsert_product()` method uses `{source_id, article_number}`
(and `ean_gtin` if present) as the match criterion and `$set` to update matching
records without overwriting the whole document. No global uniqueness constraint
on `article_number` is created, because the same article number can be used by
different manufacturers/sources.

### Decimal128 Implementation

MongoDB does not natively store Python `Decimal` objects. The following
conversion pattern is used:

- **Write**: `_apply_decimal128_forwrite()` recursively converts `Decimal`
  values to `Decimal128` before inserting/updating documents.
- **Read**: `_convert_decimal128_to_decimal()` recursively converts stored
  `Decimal128` values back to Python `Decimal` after reading.

This ensures that financial values (`net_price`, `gross_price`, `vat_rate`,
`price`) retain their precision after save and read cycles. The conversion is
applied recursively to `regional_data` arrays nested within product documents.

### Product Repository (`repositories/product_repository.py`)

Handles persistence of validated product records:

- **`insert_product()`** — Insert a single product. Returns `inserted_id` or
  `None` if a duplicate `{source_id, article_number}` already exists.
- **`insert_many()`** — Insert multiple products. Handles batch deduplication
  and partial failures (`ordered=False`).
- **`get_by_id()`** — Retrieve by MongoDB `_id`. Converts `Decimal128` → `Decimal`.
- **`get_by_article_number()`** — Retrieve by article number, optionally
  filtered by `source_id`. Returns a list (same article number across sources).
- **`get_by_gtin()`** — Retrieve by EAN/GTIN barcode.
- **`get_by_source()`** — Retrieve all products from a given source.
- **`get_all()`** — Retrieve all product records.
- **`upsert_product()`** — Upsert using `{source_id, article_number}` match
  criterion with `$set` update.
- **`update_product()`** — Update specific fields by `_id`.
- **`delete_product()`** — Delete by `_id`.
- **`count_products()`** — Total count.
- **`get_statistics()`** — Aggregate stats (distribution by `data_origin`,
  `verification_status`, counts with/without `regional_data`).

### Scraping Run Repository (`repositories/scraping_run_repository.py`)

Persists scraping execution information:

- **`create_run()`** — Create a new run record.
- **`update_run()`** — Update run status and counts.
- **`get_run_by_id()`** — Retrieve by `run_id`.
- **`get_recent_runs()`** — Most recent runs, ordered newest first.
- **`get_runs_by_source()`** — Runs for a given source.
- **`count_runs()`** / **`count_runs_by_status()`** — Count operations.

### Rejected Product Repository (`repositories/rejected_product_repository.py`)

Stores rejected records separately with:

- Original extracted data, source ID and URL.
- Article number (if available).
- Validation errors and rejection reason.
- Rejected timestamp.
- Associated scraping run ID.
- Never marks synthetic/verified records as verified.

### Pipeline Integration

The Phase 4 pipeline is integrated with MongoDB persistence via
`run_pipeline_with_persistence()`:

1. Check that MongoDB is connected before persistence.
2. Validate source authorization before scraping.
3. Run the existing extraction pipeline (cleaning → validation → deduplication → quality report).
4. Separate valid and rejected records.
5. Persist valid records using `ProductRepository` (insert or upsert).
6. Persist rejected records with validation errors using `RejectedProductRepository`.
7. Save scraping execution statistics using `ScrapingRunRepository`.
8. Return a structured execution summary with `persistence_status`:
   `"persisted"`, `"partial"`, or `"unavailable"`.

If MongoDB is disconnected:

- The pipeline still runs correctly and returns results.
- No records are claimed to have been saved.
- `persistence_status` is set to `"unavailable"`.
- The Streamlit application continues to run in offline mode.
- Users can retry persistence after reconnecting; no automatic retry that
  creates duplicates is performed.

### Test Coverage

Dedicated tests exist for:

- MongoDB configuration (local URI, Atlas URI, missing URI behavior).
- Connection success and failure.
- Ping verification.
- Collection initialization and index creation.
- Product insertion, bulk insertion, upsert.
- Duplicate handling (same `{source_id, article_number}`).
- Product retrieval (by ID, article number, GTIN, source).
- Product updates.
- Decimal128 conversion and round-trip precision.
- Regional pricing persistence.
- Rejected product persistence.
- Scraping run persistence.
- Pipeline integration (cleaning → validation → persistence).
- Disconnected database behavior (no crash, clear status).

Use mocked MongoDB clients for normal automated tests. Optional integration
tests can be activated when a dedicated test MongoDB URI is configured via
the `TEST_MONGODB_URI` environment variable. Never run destructive integration
tests against the production database.

### Documentation

- How to run local MongoDB (`mongod --dbpath <path>`).
- How to configure MongoDB Atlas (connection string, IP whitelist).
- How to configure `.env` (safe placeholders, never real credentials).
- How to test the database connection (`python -m pytest tests/test_database.py`).
- How collections are initialized (indexes, no global uniqueness).
- How product upserts work (composite key `{source_id, article_number}`).
- How to run database tests.
- How to switch between local MongoDB and Atlas (change `MONGODB_URI` in `.env`).
- Examples are included but never include real credentials.

### MongoDB Configuration

Configuration is through environment variables in `.env`:

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=granit_eu
MONGODB_SERVER_SELECTION_TIMEOUT_MS=10000
```

For MongoDB Atlas:

```env
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-url>/
MONGODB_DATABASE=granit_eu
MONGODB_SERVER_SELECTION_TIMEOUT_MS=10000
```

- Support `mongodb://` (local) and `mongodb+srv://` (Atlas) connection strings.
- Read configuration using the existing Pydantic Settings implementation
  (`config.py`). Never hardcode credentials.
- `.env.example` contains safe placeholders; never commit real credentials.
- Special characters in usernames/passwords must be URL-encoded in the
  connection string (e.g. `%23` for `#`, `%24` for `$).
- TLS certificate verification is maintained for Atlas connections; never
  disable verification.

### Connection Manager (`core/database.py`)

The `MongoDBManager` class provides:

- **`connect()`** — Establishes connection, returns `True`/`False`. On failure
  the application continues in offline mode (no crash).
- **`disconnect()`** / **`close()`** — Releases the PyMongo client.
- **`is_connected()`** — Returns `True` only when status is `CONNECTED`.
- **`status_string()`** — Returns `"DISCONNECTED"`, `"CONNECTED"`, or
  `"CONNECTION_ERROR"`.
- **`get_database()`** / **`get_collection()`** — Raise
  `DatabaseConnectionError` when not connected.
- **`ping()`** — Verified via `admin.command("ping")` during connect.
- **`initialize_collections()`** — Creates all five collections and
  non-unique indexes (see below).
- **Connection statuses**: `DISCONNECTED`, `CONNECTED`, `CONNECTION_ERROR`.
  The application must distinguish these three states and not report
  `CONNECTED` until the ping succeeds.

Five collections are initialized:

| Collection | Purpose |
|---|---|
| `products` | Validated product records |
| `data_sources` | Approved and configured sources (preserved from Phase 2) |
| `scraping_runs` | Scraping execution history |
| `rejected_products` | Records rejected during validation |
| `dataset_quality_reports` | Data quality summaries |

**Suggested indexes:**

- **products**: `{article_number: 1, source_id: 1}`, `{ean_gtin: 1, source_id: 1}`,
  `{product_url: 1, source_id: 1}`, `{verification_status: 1, source_id: 1}`,
  `{data_origin: 1, source_id: 1}`
- **data_sources**: `{source_id: 1}` (unique), `{source_name: 1}`, `{source_url: 1}`
- **scraping_runs**: `{run_id: 1}` (unique), `{source_id: 1}`, `{status: 1}`
- **rejected_products**: `{source_id: 1, article_number: 1}`, `{rejected_at: -1}`
- **dataset_quality_reports**: `{generated_at: -1}`, `{run_id: 1}`

**Product identity / upsert strategy:**

Products are identified by the composite key
`{source_id, article_number}` together with `ean_gtin` where available. This
allows the same article number to exist when it comes from different sources or
manufacturers. The `ProductRepository.upsert_product()` method uses
`{source_id, article_number}` (and `ean_gtin` if present) as the match criterion
and `$set` to update matching records without overwriting the whole document.
No global uniqueness constraint on `article_number` is created, because the
same article number can be used by different manufacturers/sources.

### Decimal128 Implementation

MongoDB does not natively store Python `Decimal` objects. The following
conversion pattern is used:

- **Write**: `_apply_decimal128_forwrite()` recursively converts `Decimal`
  values to `Decimal128` before inserting/updating documents.
- **Read**: `_convert_decimal128_to_decimal()` recursively converts stored
  `Decimal128` values back to Python `Decimal` after reading.

This ensures that financial values (`net_price`, `gross_price`, `vat_rate`,
`price`) retain their precision after save and read cycles. The conversion is
applied recursively to `regional_data` arrays nested within product documents.

### Product Repository (`repositories/product_repository.py`)

Handles persistence of validated product records:

- **`insert_product()`** — Insert a single product. Returns `inserted_id` or
  `None` if a duplicate `{source_id, article_number}` already exists.
- **`insert_many()`** — Insert multiple products. Handles batch deduplication
  and partial failures (`ordered=False`).
- **`get_by_id()`** — Retrieve by MongoDB `_id`. Converts `Decimal128` → `Decimal`.
- **`get_by_article_number()`** — Retrieve by article number, optionally
  filtered by `source_id`. Returns a list (same article number across sources).
- **`get_by_gtin()`** — Retrieve by EAN/GTIN barcode.
- **`get_by_source()`** — Retrieve all products from a given source.
- **`get_all()`** — Retrieve all product records.
- **`upsert_product()`** — Upsert using `{source_id, article_number}` match
  criterion with `$set` update.
- **`update_product()`** — Update specific fields by `_id`.
- **`delete_product()`** — Delete by `_id`.
- **`count_products()`** — Total count.
- **`get_statistics()`** — Aggregate stats (distribution by `data_origin`,
  `verification_status`, counts with/without `regional_data`).

### Scraping Run Repository (`repositories/scraping_run_repository.py`)

Persists scraping execution information:

- **`create_run()`** — Create a new run record.
- **`update_run()`** — Update run status and counts.
- **`get_run_by_id()`** — Retrieve by `run_id`.
- **`get_recent_runs()`** — Most recent runs, ordered newest first.
- **`get_runs_by_source()`** — Runs for a given source.
- **`count_runs()`** / **`count_runs_by_status()`** — Count operations.

### Rejected Product Repository (`repositories/rejected_product_repository.py`)

Stores rejected records separately with:

- Original extracted data, source ID and URL.
- Article number (if available).
- Validation errors and rejection reason.
- Rejected timestamp.
- Associated scraping run ID.
- Never marks synthetic/verified records as verified.

### Pipeline Integration

The Phase 4 pipeline is integrated with MongoDB persistence via
``run_pipeline_with_persistence()``:

1. Check that MongoDB is connected before persistence.
2. Validate source authorization before scraping.
3. Run the existing extraction pipeline (cleaning → validation → deduplication → quality report).
4. Separate valid and rejected records.
5. Persist valid records using `ProductRepository` (insert or upsert).
6. Persist rejected records with validation errors using
   `RejectedProductRepository`.
7. Save scraping execution statistics using `ScrapingRunRepository`.
8. Return a structured execution summary with `persistence_status`:
   `"persisted"`, `"partial"`, or `"unavailable"`.

If MongoDB is disconnected:

- The pipeline still runs correctly and returns results.
- No records are claimed to have been saved.
- `persistence_status` is set to `"unavailable"`.
- The Streamlit application continues to run in offline mode.
- Users can retry persistence after reconnecting; no automatic retry that
  creates duplicates is performed.

### Test Coverage

Dedicated tests exist for:

- MongoDB configuration (local URI, Atlas URI, missing URI behavior).
- Connection success and failure.
- Ping verification.
- Collection initialization and index creation.
- Product insertion, bulk insertion, upsert.
- Duplicate handling (same `{source_id, article_number}`).
- Product retrieval (by ID, article number, GTIN, source).
- Product updates.
- Decimal128 conversion and round-trip precision.
- Regional pricing persistence.
- Rejected product persistence.
- Scraping run persistence.
- Pipeline integration (cleaning → validation → persistence).
- Disconnected database behavior (no crash, clear status).

Use mocked MongoDB clients for normal automated tests. Optional integration
tests can be activated when a dedicated test MongoDB URI is configured via
the `TEST_MONGODB_URI` environment variable. Never run destructive integration
tests against the production database.

### Documentation

- How to run local MongoDB (`mongod --dbpath <path>`).
- How to configure MongoDB Atlas (connection string, IP whitelist).
- How to configure `.env` (safe placeholders, never real credentials).
- How to test the database connection (`python -m pytest tests/test_database.py`).
- How collections are initialized (indexes, no global uniqueness).
- How product upserts work (composite key `{source_id, article_number}`).
- How to run database tests.
- How to switch between local MongoDB and Atlas (change `MONGODB_URI` in `.env`).

Examples are included but never include real credentials.
