# GRANIT EU Data Scraper - Phase 2 (Data Model & Source Management)

Lightweight Python application for collecting approved product data for the
GRANIT Parts EU dataset. Phase 1 established the project foundation
(configuration, MongoDB connectivity, logging, exceptions, Streamlit shell).
Phase 2 finalizes the product data model, MongoDB collection architecture,
data-source management and extraction metadata.

No actual web scraping is implemented in this phase.

## Technology Stack

- Python 3.12
- Streamlit - application UI
- PyMongo - MongoDB driver
- Requests - HTTP client (planned for scraping)
- BeautifulSoup4 - HTML parsing (planned for scraping)
- Pandas - data handling
- OpenPyXL - Excel export (planned)
- Pydantic / Pydantic Settings - configuration and data validation
- python-dotenv - environment variable loading
- Pytest - testing

## Project Structure

```
web_scrapper/
    app.py                    # Streamlit application (Data Sources page functional)
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
        product.py            # Final Pydantic product data model

    scraper/__init__.py       # Scraping engine (Phase 3)
    services/
        __init__.py
        source.py             # Source management service
    exporters/__init__.py     # Excel exporters (Phase 3)
    ui/__init__.py            # UI components (Phase 3)

    tests/
        __init__.py
        test_app.py           # Streamlit app startup/rendering tests
        test_config.py        # Configuration tests
        test_database.py      # MongoDB connection + collection init tests (mocked)
        test_product.py       # Product model / regional data / provenance tests
        test_source.py        # Source management service tests

    output/.gitkeep           # Generated export output directory
```

## Final Product Schema

The `Product` model (Pydantic v2) organizes data into logical sections:

**A. Product master**
- `article_number` (mandatory) - unique article number
- `product_name` (mandatory) - human readable product name
- `sku`, `ean_gtin`, `description`, `short_description`, `product_type`, `product_url`, `image_urls`

**B. Manufacturer and classification**
- `manufacturer`, `brand`, `supplier`, `category`, `subcategory`

**C. Technical specifications**
- `dimensions`, `weight`, `material`, `technical_specifications`, `compatibility`

**D. Compliance**
- `ce_marking_status`, `applicable_regulations`, `compliance_certificates`, `country_of_origin`

**E. Inventory and logistics**
- `inventory_status`, `inventory_quantity`, `warehouse`, `shipping_method`, `delivery_days`

**Regional data** (nested array, multiple EU country entries)
- `country`, `country_code` (ISO 3166-1 alpha-2), `currency` (ISO 4217)
- `net_price`, `vat_rate`, `gross_price` (Decimal)
- `price_source`, `effective_date`

**Data provenance**
- `data_origin` (approved_public_source / authorized_api / manual_entry / synthetic)
- `source_id`, `source_url`, `collected_at`
- `verification_status` (verified / partially_verified / not_verified / pending)
- `is_synthetic`, `last_updated_at`

Unavailable or restricted information supports null values. Mandatory
identifiers are `article_number` and `product_name`.

## EU Regional Pricing Design

A single product can have multiple country-specific commercial records
stored in the embedded `regional_data` array. Each entry uses ISO country
codes (2-letter uppercase) and ISO 4217 currency codes (3-letter uppercase).

Validation:
- Country code must match `^[A-Z]{2}$`.
- Currency code must match `^[A-Z]{3}$`.
- Prices must be non-negative.
- VAT rate must be between 0 and 100.
- Gross price consistency is checked when `net_price`, `vat_rate` and
  `gross_price` are all present (`gross ≈ net × (1 + vat/100)`).

Monetary values use `Decimal` for precision. Not every product is assumed
to be sold in every EU country, and no country-specific prices are
hardcoded as verified data.

## Data Provenance

Every product supports provenance fields. Supported data origins:
- `approved_public_source`
- `authorized_api`
- `manual_entry`
- `synthetic`

Supported verification statuses:
- `verified`
- `partially_verified`
- `not_verified`
- `pending`

Synthetic records must never be marked as `verified` (enforced by model
validation). Field-level provenance is supported through `price_source` on
regional entries and `source_id`/`source_url` at the product level, allowing
actual and synthetic values to coexist in one product.

## MongoDB Collection Structure

Database: `granit_eu`

Collections:
1. **products** - product records with embedded `regional_data` and provenance
   - Indexes (non-unique): `article_number`, `ean_gtin`, `category`
2. **data_sources** - registered data sources and authorization
   - Indexes (non-unique): `source_name`, `source_url`
3. **scraping_runs** - scraping run history and results
   - Indexes (non-unique): `run_id`, `source_id`, `status`

No uniqueness constraints are created that would prevent multiple source
records or regional prices.

## Source Authorization Workflow

Source fields: `source_id`, `source_name`, `source_url`, `source_type`
(website / api / csv / manual), `authorization_status`
(pending / approved / rejected), `allowed_usage`, `enabled`, `notes`,
`created_at`, `updated_at`.

- New sources default to `authorization_status = "pending"`.
- Sources are **never** automatically approved.
- Only `approved` **and** `enabled` sources are eligible for automated
  extraction.
- Pending or rejected sources can never be scraped.
- GRANIT is not automatically marked as approved.

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

The **Data Sources** page supports registering a source URL, selecting a
source type, viewing/updating authorization and enabled status, and clearly
indicates that pending sources cannot be scraped.

The application starts successfully even when MongoDB is unavailable and
shows a disconnected status instead of crashing.

## Running Tests

Tests do not require a live MongoDB server, GRANIT website, or real
credentials (connections and sources are mocked).

```powershell
python -m pytest
```

## Known Limitations

- No actual web scraping, Excel export, or full product CRUD yet
  (deferred to later phases).
- Streamlit `st.rerun()` is used in the Data Sources page; requires a
  live Streamlit session (not exercised by AppTest beyond startup/render).
- Decimal monetary values are used in the Pydantic model; BSON conversion
  for storage is handled at the persistence layer in a later phase.
