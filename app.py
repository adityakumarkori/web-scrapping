"""GRANIT EU Data Manager - Streamlit application shell.

A minimal, professional application shell. It starts successfully even when
MongoDB is unavailable and shows a clear disconnected status instead of
crashing. Full page functionality is implemented in later phases.
"""

import streamlit as st

from config import settings
from core.database import mongodb
from core.exceptions import DatabaseConnectionError
from core.logging import get_logger, setup_logging

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


def _render_dashboard(connected: bool) -> None:
    """Render the dashboard landing page."""
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
                product_count = mongodb.get_collection("products").estimated_document_count()
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


def _render_placeholder(page: str) -> None:
    """Render a placeholder page for unimplemented navigation targets."""
    st.info(f"{page} page - coming soon in Phase 2.")


def main() -> None:
    st.set_page_config(
        page_title="GRANIT EU Data Manager",
        page_icon="\U0001F4E6",
        layout="wide",
    )

    st.title("GRANIT EU Data Manager")
    st.caption("Approved product data collection for the GRANIT Parts EU dataset")

    # Sidebar navigation
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
        _render_placeholder(page)
    elif page == "Products":
        _render_placeholder(page)
    elif page == "Database":
        _render_placeholder(page)
    elif page == "Excel Export":
        _render_placeholder(page)


if __name__ == "__main__":
    main()
