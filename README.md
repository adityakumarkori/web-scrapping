# GRANIT EU Data Scraper - Phase 1 (Project Foundation)

Lightweight Python application foundation for collecting approved product
data for the GRANIT Parts EU dataset. This phase establishes project
structure, configuration, MongoDB connectivity, logging, exceptions, a
preliminary product model, and a Streamlit application shell. No actual
web scraping is implemented in this phase.

## Technology Stack

- Python 3.12
- Streamlit - application UI
- PyMongo - MongoDB driver
- Requests - HTTP client (planned for scraping)
- BeautifulSoup4 - HTML parsing (planned for scraping)
- Pandas - data handling
- OpenPyXL - Excel export
- Pydantic / Pydantic Settings - configuration and data validation
- python-dotenv - environment variable loading
- Pytest - testing

## Project Structure

```
web_scrapper/
    app.py                    # Streamlit application shell
    config.py                 # Pydantic settings configuration
    requirements.txt          # Pinned Python dependencies
    .env.example              # Documented environment variable placeholders
    .gitignore                # Git ignore rules
    README.md                 # This file

    core/
        __init__.py
        database.py           # MongoDB connection manager
        logging.py            # Centralized logging
        exceptions.py         # Reusable application exceptions

    models/
        __init__.py
        product.py            # Pydantic product model

    scraper/__init__.py       # Scraping engine (Phase 2)
    services/__init__.py      # Business services (Phase 2)
    exporters/__init__.py     # Excel exporters (Phase 2)
    ui/__init__.py            # UI components (Phase 2)

    tests/
        test_config.py        # Configuration tests
        test_database.py      # MongoDB connection tests (mocked)
        test_app.py           # Streamlit app startup/rendering tests

    output/.gitkeep           # Generated export output directory
```

## Python Environment Setup

1. Create and activate a virtual environment (Python 3.12):

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

## Environment Configuration

1. Copy `.env.example` to `.env`:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env` and set values for your environment. Never commit real
   credentials. The `.env` file is ignored by git.

   Key settings:

   - `APP_NAME`, `APP_ENV`, `DEBUG`
   - `MONGODB_URI` - full MongoDB connection string (no hardcoded creds)
   - `MONGODB_DATABASE` - defaults to `granit_eu`
   - `LOG_LEVEL`
   - `MAX_PRODUCT_RECORDS` - defaults to `100`
   - `HTTP_REQUEST_TIMEOUT`

## MongoDB Setup

Initial collections used by the application:

- `products`
- `data_sources`
- `scraping_runs`

A local MongoDB instance at `mongodb://localhost:27017` is the default.
The application starts successfully even when MongoDB is unavailable and
displays a disconnected status instead of crashing.

## Running the Streamlit Application

```powershell
streamlit run app.py
```

The app opens at `http://localhost:8501` by default. Sidebar navigation
includes Dashboard, Data Sources, Products, Database, and Excel Export.

## Running Tests

Tests do not require an active MongoDB server (connections are mocked).

```powershell
pytest
```

## License

Internal project - no license specified.
