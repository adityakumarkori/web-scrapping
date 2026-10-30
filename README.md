# GRANIT EU Data Scraper - Phase 3 (Web Scraping Engine)

Lightweight Python application for collecting approved product data for the
GRANIT Parts EU dataset. Phase 1 established the project foundation
(configuration, MongoDB connectivity, logging, exceptions, Streamlit shell).
Phase 2 finalized the product data model, MongoDB collection architecture,
data-source management and extraction metadata. Phase 3 implements a reusable
web scraping engine that extracts product information from approved sources
and returns structured product records.

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
  local fixtures and mocked HTTP responses.
- No Excel export or full product CRUD yet (deferred to later phases).
- Product documents are not persisted to MongoDB in this phase; the
  `ExtractionResult` is structured for handoff to a later persistence layer.
- Streamlit `st.rerun()` is used in the Data Sources page; requires a live
  Streamlit session (not exercised by AppTest beyond startup/render).
- Decimal monetary values are used in the Pydantic model; BSON conversion
  for storage is handled at the persistence layer in a later phase.
- No Selenium, Playwright or browser automation is used.

## Confirmation

No unauthorized live GRANIT website scraping was performed. All scraping
behavior is validated against local fixtures and mocked responses, and source
authorization is enforced before any network access.
