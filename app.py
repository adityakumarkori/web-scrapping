"""GRANIT EU Data Manager - Streamlit application.

A lightweight application shell that starts successfully even when MongoDB is
unavailable and shows a clear disconnected status instead of crashing.

Phase 2 adds a functional Data Sources page for registering and managing
data sources. Products and Database pages reflect the new schema and
collection structure. Full scraping and Excel export come in later phases.
"""

from typing import Optional

import streamlit as st

from config import settings
from core.database import (
    COLLECTION_DATA_SOURCES,
    COLLECTION_PRODUCTS,
    COLLECTION_SCRAPING_RUNS,
    mongodb,
)
from core.exceptions import DatabaseConnectionError, DataValidationError
from core.logging import get_logger, setup_logging
from services.source import (
    AUTHORIZATION_STATUSES,
    SOURCE_TYPES,
    SourceService,
    validate_source_url,
)
from scraper.client import HttpClient
from scraper.runner import ScrapingRunner

setup_logging()
logger = get_logger(__name__)

PAGES = [
    "Dashboard",
    "Data Sources",
    "Products",
    "Database",
    "Excel Export",
]


def _initialize_mongodb() -> bool:
    """Initialize and test the MongoDB connection once per session."""
    if "mongodb_connected" not in st.session_state:
        try:
            connected = mongodb.connect()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Unexpected error during MongoDB connect: %s", exc)
            connected = False
        st.session_state["mongodb_connected"] = connected
    return st.session_state.get("mongodb_connected", False)


def _get_source_service() -> Optional[SourceService]:
    """Return a SourceService when MongoDB is connected, else None."""
    if not st.session_state.get("mongodb_connected", False):
        return None
    try:
        return SourceService()
    except DatabaseConnectionError as exc:
        logger.warning("Unable to create source service: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def _render_dashboard(connected: bool) -> None:
    st.subheader("Dashboard")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Application", settings.app_name)
    with col2:
        status = "Connected" if connected else "Disconnected"
        st.metric("MongoDB", status)
    with col3:
        product_count = None
        if connected:
            try:
                product_count = mongodb.get_collection(COLLECTION_PRODUCTS).estimated_document_count()
            except (DatabaseConnectionError, Exception) as exc:  # noqa: BLE001
                logger.warning("Unable to fetch product count: %s", exc)
        st.metric("Products", product_count if product_count is not None else "N/A")

    if connected:
        st.success("MongoDB connection is active.")
    else:
        st.error(
            "MongoDB is unavailable. The application continues to run in offline "
            "mode. Connect a MongoDB instance to store product data."
        )

    st.info("Product count placeholder - full product management comes in Phase 2.")


# ---------------------------------------------------------------------------
# Data Sources
# ---------------------------------------------------------------------------
def _render_data_sources(connected: bool) -> None:
    st.subheader("Data Sources")
    st.caption("Register and manage data sources for product collection.")

    if not connected:
        st.error(
            "MongoDB is unavailable. Source management requires a MongoDB "
            "connection. Connect a MongoDB instance to register sources."
        )
        return

    service = _get_source_service()
    if service is None:
        st.error("Unable to access the data_sources collection.")
        return

    st.markdown("### Register a new source")
    with st.form("add_source_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            source_name = st.text_input("Source name", placeholder="e.g. GRANIT EU")
            source_url = st.text_input("Source URL", placeholder="https://example.com")
            source_type = st.selectbox("Source type", options=sorted(SOURCE_TYPES), index=0)
        with col2:
            authorization_status = st.selectbox(
                "Authorization status",
                options=sorted(AUTHORIZATION_STATUSES),
                index=0,
                help="New sources default to pending and cannot be scraped until approved.",
            )
            enabled = st.checkbox("Enabled", value=True)
            notes = st.text_area("Notes", placeholder="Optional notes")
        submitted = st.form_submit_button("Register source")

    if submitted:
        try:
            service.add_source(
                source_name=source_name,
                source_url=source_url,
                source_type=source_type,
                authorization_status=authorization_status,
                enabled=enabled,
                notes=notes or None,
            )
            st.success("Source registered successfully.")
            st.rerun()
        except DataValidationError as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to register source")
            st.error(f"Failed to register source: {exc}")

    st.markdown("---")
    st.markdown("### Registered sources")

    try:
        sources = service.list_sources()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unable to list sources")
        st.error(f"Unable to load sources: {exc}")
        sources = []

    if not sources:
        st.info("No data sources registered yet.")
        return

    for source in sources:
        source_id = source.get("source_id", "unknown")
        status = source.get("authorization_status", "pending")
        enabled = source.get("enabled", False)
        eligible = SourceService.is_eligible_for_extraction(source)

        with st.expander(f"{source.get('source_name', 'Unnamed')} ({source_id[:8]}...)"):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.text(f"Type: {source.get('source_type', '-')}")
                st.text(f"URL: {source.get('source_url', '-')}")
            with c2:
                badge = "APPROVED" if status == "approved" else status.upper()
                st.text(f"Authorization: {badge}")
                st.text(f"Enabled: {'Yes' if enabled else 'No'}")
            with c3:
                if eligible:
                    st.success("Eligible for extraction")
                else:
                    st.error("Not eligible for extraction")
                    st.caption("Pending or rejected sources cannot be scraped.")

            st.markdown("#### Update source")
            with st.form(f"update_form_{source_id}"):
                new_name = st.text_input("Source name", value=source.get("source_name", ""), key=f"name_{source_id}")
                new_url = st.text_input("Source URL", value=source.get("source_url", ""), key=f"url_{source_id}")
                new_type = st.selectbox(
                    "Source type",
                    options=sorted(SOURCE_TYPES),
                    index=sorted(SOURCE_TYPES).index(source.get("source_type", "website")) if source.get("source_type") in SOURCE_TYPES else 0,
                    key=f"type_{source_id}",
                )
                new_status = st.selectbox(
                    "Authorization status",
                    options=sorted(AUTHORIZATION_STATUSES),
                    index=sorted(AUTHORIZATION_STATUSES).index(status) if status in AUTHORIZATION_STATUSES else 0,
                    key=f"status_{source_id}",
                )
                new_enabled = st.checkbox("Enabled", value=bool(enabled), key=f"enabled_{source_id}")
                new_notes = st.text_area("Notes", value=source.get("notes") or "", key=f"notes_{source_id}")
                update_submitted = st.form_submit_button("Save changes")

            if update_submitted:
                try:
                    service.update_source(
                        source_id,
                        {
                            "source_name": new_name,
                            "source_url": new_url,
                            "source_type": new_type,
                            "authorization_status": new_status,
                            "enabled": new_enabled,
                            "notes": new_notes or None,
                        },
                    )
                    st.success("Source updated.")
                    st.rerun()
                except DataValidationError as exc:
                    st.error(str(exc))
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to update source")
                    st.error(f"Failed to update source: {exc}")

            col_del, col_auth = st.columns(2)
            with col_del:
                if st.button("Disable source", key=f"disable_{source_id}"):
                    try:
                        service.disable_source(source_id)
                        st.success("Source disabled.")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Failed to disable source: {exc}")
            with col_auth:
                if st.button("Enable source", key=f"enable_{source_id}"):
                    try:
                        service.enable_source(source_id)
                        st.success("Source enabled.")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Failed to enable source: {exc}")

    _render_extraction_controls(service)


# ---------------------------------------------------------------------------
# Extraction controls
# ---------------------------------------------------------------------------
def _render_extraction_controls(service: SourceService) -> None:
    """Render extraction controls for eligible (approved + enabled) sources."""
    st.markdown("---")
    st.markdown("### Start extraction")

    try:
        sources = service.list_sources()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unable to list sources for extraction")
        st.error(f"Unable to load sources: {exc}")
        return

    eligible_sources = [
        s for s in sources if SourceService.is_eligible_for_extraction(s)
    ]
    if not eligible_sources:
        st.info(
            "No approved and enabled sources available for extraction. "
            "Register a source and set its authorization to approved and "
            "enable it before extracting."
        )
        return

    source_options = {
        f"{s.get('source_name', 'Unnamed')} ({s.get('source_id', '')[:8]})": s
        for s in eligible_sources
    }
    selected_label = st.selectbox("Select an approved source", options=list(source_options.keys()))
    selected_source = source_options[selected_label]

    st.text(f"Source URL: {selected_source.get('source_url', '-')}")

    default_url = selected_source.get("source_url", "")
    start_url = st.text_input(
        "Starting product or catalogue URL",
        value=default_url,
        help="Must belong to the approved source domain.",
    )
    max_records = st.number_input(
        "Maximum records",
        min_value=1,
        max_value=100,
        value=min(100, settings.max_product_records),
        step=1,
    )

    if st.button("Start extraction", key=f"extract_{selected_source.get('source_id')}"):
        if not start_url:
            st.error("Please enter a starting URL.")
            return
        try:
            runner = ScrapingRunner(source_service=service)
            with st.spinner("Extracting products..."):
                result = runner.run(
                    source_id=selected_source.get("source_id"),
                    start_url=start_url,
                    max_records=int(max_records),
                )
            st.session_state["extraction_result"] = result
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Extraction failed")
            st.error(f"Extraction failed: {exc}")

    result = st.session_state.get("extraction_result")
    if result:
        st.markdown("#### Extraction result")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Status", result.status)
        with c2:
            st.metric("Found", result.records_found)
        with c3:
            st.metric("Extracted", result.records_extracted)
        with c4:
            st.metric("Skipped / Failed", result.records_skipped + result.records_failed)

        if result.errors:
            st.markdown("**Errors / skipped:**")
            for err in result.errors[:20]:
                st.caption(f"- {err}")

        if result.products:
            st.markdown(f"**Sample products ({min(5, len(result.products))}):**")
            for p in result.products[:5]:
                st.caption(f"- {p.article_number}: {p.product_name} ({p.data_origin})")

        if st.button("Clear result", key="clear_extraction_result"):
            st.session_state.pop("extraction_result", None)
            st.rerun()


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
def _render_products(connected: bool) -> None:
    st.subheader("Products")
    st.caption("Product records following the GRANIT EU schema.")

    st.markdown("### Product schema sections")
    st.markdown(
        "- **Product master:** article_number, product_name, sku, ean_gtin, "
        "description, short_description, product_type, product_url, image_urls"
    )
    st.markdown(
        "- **Manufacturer and classification:** manufacturer, brand, supplier, "
        "category, subcategory"
    )
    st.markdown(
        "- **Technical specifications:** dimensions, weight, material, "
        "technical_specifications, compatibility"
    )
    st.markdown(
        "- **Compliance:** ce_marking_status, applicable_regulations, "
        "compliance_certificates, country_of_origin"
    )
    st.markdown(
        "- **Inventory and logistics:** inventory_status, inventory_quantity, "
        "warehouse, shipping_method, delivery_days"
    )
    st.markdown(
        "- **Regional data:** one entry per EU country (country, country_code, "
        "currency, net_price, vat_rate, gross_price, price_source, effective_date)"
    )
    st.markdown(
        "- **Data provenance:** data_origin, source_id, source_url, collected_at, "
        "verification_status, is_synthetic, last_updated_at"
    )

    product_count = None
    if connected:
        try:
            product_count = mongodb.get_collection(COLLECTION_PRODUCTS).estimated_document_count()
        except (DatabaseConnectionError, Exception) as exc:  # noqa: BLE001
            logger.warning("Unable to fetch product count: %s", exc)
    st.metric("Products in database", product_count if product_count is not None else "N/A")

    if not connected:
        st.error("MongoDB is unavailable. Product records cannot be listed or stored.")
    else:
        st.info("Full product create/read/update/delete comes in Phase 3.")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def _render_database(connected: bool) -> None:
    st.subheader("Database")
    st.caption("MongoDB collections and connection status.")

    collections = [
        (COLLECTION_PRODUCTS, "Product records with embedded regional_data"),
        (COLLECTION_DATA_SOURCES, "Registered data sources and authorization"),
        (COLLECTION_SCRAPING_RUNS, "Scraping run history and results"),
    ]

    st.markdown("### Collections")
    for name, description in collections:
        count = None
        if connected:
            try:
                count = mongodb.get_collection(name).estimated_document_count()
            except (DatabaseConnectionError, Exception) as exc:  # noqa: BLE001
                logger.warning("Unable to count %s: %s", name, exc)
        st.markdown(f"- **{name}**: {description}")
        st.caption(f"  Documents: {count if count is not None else 'N/A'}")

    st.markdown("### Indexes (non-unique)")
    st.markdown(
        "- **products:** article_number, ean_gtin, category\n"
        "- **data_sources:** source_name, source_url\n"
        "- **scraping_runs:** run_id, source_id, status"
    )

    if connected:
        st.success("MongoDB connection is active.")
    else:
        st.error("MongoDB is unavailable. Connect a MongoDB instance to use collections.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="GRANIT EU Data Manager",
        page_icon="\U0001F4E6",
        layout="wide",
    )

    st.title("GRANIT EU Data Manager")
    st.caption("Approved product data collection for the GRANIT Parts EU dataset")

    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", PAGES, index=0)

    st.sidebar.markdown("---")
    st.sidebar.subheader("Environment")
    st.sidebar.text(f"App: {settings.app_name}")
    st.sidebar.text(f"Environment: {settings.app_env}")
    st.sidebar.text(f"Debug: {settings.debug}")
    st.sidebar.text(f"Database: {settings.mongodb_database}")

    connected = _initialize_mongodb()
    if connected:
        st.sidebar.success("MongoDB: Connected")
    else:
        st.sidebar.error("MongoDB: Disconnected")

    if page == "Dashboard":
        _render_dashboard(connected)
    elif page == "Data Sources":
        _render_data_sources(connected)
    elif page == "Products":
        _render_products(connected)
    elif page == "Database":
        _render_database(connected)
    elif page == "Excel Export":
        st.subheader("Excel Export")
        st.info("Excel export of up to 100 product records comes in Phase 2 / Phase 3.")


if __name__ == "__main__":
    main()
