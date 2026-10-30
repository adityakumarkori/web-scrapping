"""GRANIT EU Data Manager - Streamlit application.

A lightweight application shell that starts successfully even when MongoDB is
unavailable and shows a clear disconnected status instead of crashing.

Phase 2 adds a functional Data Sources page for registering and managing
data sources. Products and Database pages reflect the new schema and
collection structure. Full scraping and Excel export come in later phases.
"""

from typing import Optional

import json
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
    "Data Quality",
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

    # Initialize data structures
    product_count = 0
    verified_count = 0
    synthetic_count = 0
    data_sources_count = 0
    approved_sources_count = 0
    scraping_runs_count = 0
    rejected_count = 0
    avg_quality_score = 0.0

    if connected:
        try:
            # Product counts
            products_coll = mongodb.get_collection(COLLECTION_PRODUCTS)
            product_count = products_coll.estimated_document_count()

            # Verified vs synthetic
            pipeline = [
                {"$match": {"verification_status": "verified"}},
                {"$count": "total"},
            ]
            verified_result = list(products_coll.aggregate(pipeline))
            verified_count = verified_result[0]["total"] if verified_result else 0

            pipeline2 = [
                {"$match": {"is_synthetic": True}},
                {"$count": "total"},
            ]
            synthetic_result = list(products_coll.aggregate(pipeline2))
            synthetic_count = synthetic_result[0]["total"] if synthetic_result else 0

            # Data sources
            sources_coll = mongodb.get_collection(COLLECTION_DATA_SOURCES)
            data_sources_count = sources_coll.estimated_document_count()

            pipeline3 = [{"$match": {"authorization_status": "approved"}}]
            approved_result = list(sources_coll.aggregate(pipeline3))
            approved_sources_count = len(approved_result)

            # Scraping runs
            runs_coll = mongodb.get_collection(COLLECTION_SCRAPING_RUNS)
            scraping_runs_count = runs_coll.estimated_document_count()

            # Rejected products
            rejected_coll = mongodb.get_collection(COLLECTION_REJECTED_PRODUCTS)
            rejected_count = rejected_coll.estimated_document_count()

            # Average quality score (from quality reports if available, otherwise estimate)
            # For now, use a simple estimation based on record completeness
            if product_count > 0:
                # Simple estimation: count records with regional_data and verification_status
                quality_pipeline = [
                    {
                        "$project": {
                            "has_regional": {"$gt": [{"$size": "$regional_data"}, 0]},
                            "is_verified": {"$eq": ["$verification_status", "verified"]},
                        }
                    }
                ]
                quality_result = list(products_coll.aggregate(quality_pipeline))
                complete = sum(1 for r in quality_result if r.get("has_regional") and r.get("is_verified"))
                partial = sum(1 for r in quality_result if r.get("has_regional") and not r.get("is_verified"))
                incomplete = sum(1 for r in quality_result if not r.get("has_regional"))
                total_scored = complete + partial + incomplete
                if total_scored > 0:
                    avg_quality_score = round((complete * 1.0 + partial * 0.5) / total_scored * 100, 1)
                else:
                    avg_quality_score = 0.0

            # Recent activity counts (last 7 days approximation)
            # ... (could be expanded with date filtering)

        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to fetch dashboard statistics: %s", exc)

    # KPI Cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Products", product_count)
    with col2:
        st.metric("Verified Products", verified_count)
    with col3:
        st.metric("Synthetic Products", synthetic_count)
    with col4:
        st.metric("Data Sources", data_sources_count)

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.metric("Approved Sources", approved_sources_count)
    with col6:
        st.metric("Scraping Runs", scraping_runs_count)
    with col7:
        st.metric("Rejected Products", rejected_count)
    with col8:
        st.metric("Avg Data Quality Score", f"{avg_quality_score}%")

    st.markdown("---")

    # Visualizations row
    if connected:
        st.markdown("### Visualizations")
        viz_col1, viz_col2 = st.columns(2)

        # Products by category (simple bar chart data)
        with viz_col1:
            st.markdown("#### Products by Category")
            try:
                cat_pipeline = [
                    {"$group": {"_id": "$category", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 10},
                ]
                cat_results = list(products_coll.aggregate(cat_pipeline))
                if cat_results:
                    categories = [r["_id"] or "Uncategorized" for r in cat_results]
                    counts = [r["count"] for r in cat_results]
                    st.bar_chart({"category": categories, "count": counts})
                else:
                    st.info("No category data available")
            except Exception:
                st.info("Unable to load category distribution")

        # Verification status distribution
        with viz_col2:
            st.markdown("#### Verification Status Distribution")
            try:
                status_pipeline = [
                    {"$group": {"_id": "$verification_status", "count": {"$sum": 1}}},
                ]
                status_results = list(products_coll.aggregate(status_pipeline))
                if status_results:
                    status_data = {}
                    for r in status_results:
                        status_data[r["_id"]] = r["count"]
                    st.bar_chart(status_data)
                else:
                    st.info("No verification data available")
            except Exception:
                st.info("Unable to load verification distribution")

        # Products by manufacturer (top 10)
        with viz_col1:
            st.markdown("#### Top Manufacturers")
            try:
                manu_pipeline = [
                    {"$group": {"_id": "$manufacturer", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 10},
                ]
                manu_results = list(products_coll.aggregate(manu_pipeline))
                if manu_results:
                    manufacturers = [r["_id"] or "Unknown" for r in manu_results]
                    counts = [r["count"] for r in manu_results]
                    st.bar_chart(
                        {"manufacturer": manufacturers, "count": counts},
                        use_container_width=True,
                    )
                else:
                    st.info("No manufacturer data available")
            except Exception:
                st.info("Unable to load manufacturer data")

        # Data quality distribution
        with viz_col2:
            st.markdown("#### Data Quality Distribution")
            try:
                # Use the existing quality summary approach
                quality_results = {
                    "Complete": max(verified_count - synthetic_count, 0),
                    "Partial": synthetic_count,
                    "Incomplete": product_count - verified_count - synthetic_count + max(verified_count - synthetic_count, 0),
                }
                # Filter out zero values
                quality_data = {k: v for k, v in quality_results.items() if v > 0}
                if quality_data:
                    st.bar_chart(quality_data)
                else:
                    st.info("No quality data available")
            except Exception:
                st.info("Unable to load quality distribution")

    # Recent activity section
    st.markdown("---")
    st.markdown("### Recent Activity")
    activity_col1, activity_col2 = st.columns(2)

    # Recent scraping runs
    with activity_col1:
        st.markdown("#### Recent Scraping Runs")
        if connected:
            try:
                runs_coll = mongodb.get_collection(COLLECTION_SCRAPING_RUNS)
                recent_runs = list(
                    runs_coll.find({})
                    .sort("started_at", -1)
                    .limit(5)
                )
                for run in recent_runs:
                    status = run.get("status", "unknown")
                    run_id = run.get("run_id", "unknown")[:8]
                    st.caption(f"• {status} • {run_id}")
                if not recent_runs:
                    st.caption("• No runs yet")
            except Exception:
                st.caption("• Unable to load runs")

    # Recent product insertions
    with activity_col2:
        st.markdown("#### Recent Product Insertions")
        if connected:
            try:
                products_coll = mongodb.get_collection(COLLECTION_PRODUCTS)
                recent_products = list(
                    products_coll.find({})
                    .sort("_id", -1)
                    .limit(5)
                )
                for prod in recent_products:
                    an = prod.get("article_number", "N/A")[:8]
                    st.caption(f"• {an} • {prod.get('product_name', '')[:20]}")
                if not recent_products:
                    st.caption("• No products yet")
            except Exception:
                st.caption("• Unable to load products")


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
# Data Quality
# ---------------------------------------------------------------------------
def _render_data_quality(connected: bool) -> None:
    """Render the Data Quality page for assessing product record quality."""

    from services.pipeline import run_pipeline

    # Initialize session state for holding product data
    if "quality_products" not in st.session_state:
        st.session_state["quality_products"] = []

    # --- Product input section ---
    st.markdown("### Upload / Paste Product Records")
    st.markdown(
        "Paste product records as JSON (one per line) or upload a file. "
        "Each record should follow the GRANIT EU product schema."
    )

    uploaded_file = st.file_uploader(
        "Upload JSON file with product records", type=["json"], accept_multiple_files=False
    )
    manual_json = st.text_area(
        "Or paste JSON records (one per line):",
        height=200,
        help="Each line should be a valid product JSON object.",
    )

    products: List[Dict[str, Any]] = []

    if uploaded_file is not None:
        try:
            products = json.load(uploaded_file)
            st.success(f"Loaded {len(products)} records from file.")
        except Exception as exc:
            st.error(f"Failed to parse JSON file: {exc}")

    if manual_json.strip():
        try:
            records = [json.loads(line) for line in manual_json.strip().splitlines() if line.strip()]
            products.extend(records)
            st.info(f"Added {len(records)} records from text input.")
        except json.JSONDecodeError as exc:
            st.error(f"Failed to parse JSON text: {exc}")

    if not products and not st.session_state["quality_products"]:
        st.info("No product records loaded. Please upload a file or paste JSON records.")
    else:
        # Combine loaded products with previously loaded ones
        if st.session_state["quality_products"]:
            all_products = st.session_state["quality_products"] + products
        else:
            all_products = products

        # Run pipeline
        if st.button("Run Quality Assessment", key="run_quality_assessment"):
            with st.spinner("Running pipeline cleaning → validation → deduplication → quality report..."):
                result = run_pipeline(all_products)

            # Store results in session state for display
            st.session_state["quality_result"] = result
            st.session_state["quality_products"] = all_products
            st.rerun()

        # Display results if available
        result = st.session_state.get("quality_result")
        if result:
            # Quality summary
            sq = result.quality_summary
            st.markdown("### Dataset Quality Summary")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Total Records", sq["total_records"])
            with c2:
                st.metric("Valid Records", sq["valid_records"])
            with c3:
                st.metric("Invalid Records", sq["invalid_records"])

            st.progress(sq["overall_quality_percentage"] / 100)
            st.caption(f"Overall quality: {sq['overall_quality_percentage']}%")

            # Quality distribution
            st.markdown("#### Quality Distribution")
            dist = sq["quality_distribution"]
            d1, d2, d3 = st.columns(3)
            with d1:
                st.info(f"Complete: {dist['complete']}")
            with d2:
                st.info(f"Partial: {dist['partial']}")
            with d3:
                st.info(f"Incomplete: {dist['incomplete']}")

            # Missing mandatory fields
            st.markdown("#### Missing Mandatory Fields")
            mm = sq["missing_mandatory_by_field"]
            if any(mm.values()):
                for field, count in mm.items():
                    if count > 0:
                        st.caption(f"- **{field}**: {count} records")
            else:
                st.success("All records have mandatory fields present.")

            # Missing optional fields
            st.markdown("#### Missing Optional Fields")
            mo = sq["missing_optional_by_field"]
            if any(mo.values()):
                sorted_missing = sorted(mo.items(), key=lambda x: x[1], reverse=True)[:10]
                for field, count in sorted_missing:
                    st.caption(f"- **{field}**: {count} records")
            else:
                st.success("All records have optional fields filled (or none expected).")

            # Duplicate groups
            st.markdown("#### Duplicate Groups")
            if result.duplicate_groups:
                for g in result.duplicate_groups:
                    st.warning(
                        f"{g.duplicate_type}: `{g.key}` — {len(g.records)} records — {g.reason}"
                    )
            else:
                st.success("No duplicate records detected.")

            # Record-level scores
            st.markdown("#### Per-Record Quality Scores")
            scores = sq["record_scores"]
            if scores:
                avg_score = sum(scores) / len(scores)
                st.caption(f"Average quality score: {avg_score:.2f}")
                complete = sum(1 for s in scores if s >= 1.0)
                partial = sum(1 for s in scores if 0.5 <= s < 1.0)
                incomplete = sum(1 for s in scores if s < 0.5)
                st.caption(f"Complete: {complete} | Partial: {partial} | Incomplete: {incomplete}")

            # Rejected products summary
            if result.rejected_products:
                st.markdown("#### Rejected Products")
                st.caption(f"{len(result.rejected_products)} records rejected due to validation errors:")
                for item in result.rejected_products[:10]:
                    with st.expander(f"Product: {item['product'].get('article_number', 'N/A')}"):
                        for err in item["errors"][:3]:
                            st.caption(f"  - {err}")
                if len(result.rejected_products) > 10:
                    st.caption(f"... and {len(result.rejected_products) - 10} more")

            # Save button to keep products for later
            if st.button("Save Current Products", key="save_quality_products"):
                st.session_state["quality_products"] = all_products
                st.success("Products saved to session state.")

        # Button to clear and start fresh
        if st.button("Clear and Start Fresh", key="clear_quality"):
            for key in list(st.session_state.keys()):
                if "quality" in key:
                    del st.session_state[key]
            st.rerun()


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
    elif page == "Data Quality":
        _render_data_quality(connected)
    elif page == "Excel Export":
        _render_excel_export(connected)


def _render_excel_export(connected: bool) -> None:
    """Render the Excel Export page."""
    st.subheader("Excel Export")
    st.caption("Export product data to Excel format.")

    if not connected:
        st.error("MongoDB is unavailable. Export requires a MongoDB connection.")
    else:
        st.info("Excel export functionality comes in a later phase.")


if __name__ == "__main__":
    main()
