"""Scraping runner that coordinates source validation and extraction.

Coordinates:

* Source authorization validation (no network access for unauthorized sources)
* HTTP fetching via the safety-guarded HttpClient
* HTML parsing and product extraction
* Maximum record limits and pagination loop prevention
* Duplicate URL detection
* Extraction statistics and error reporting

Product documents are not persisted to MongoDB in this phase; the
extraction result can be passed to a later persistence layer.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from core.logging import get_logger
from models.product import Product
from scraper.client import HttpClient, _is_private_ip
from scraper.exceptions import (
    ExtractionError,
    ParsingError,
    ScrapingError,
    SourceAccessError,
)
from scraper.extractor import (
    build_product,
    extract_from_json_ld,
    extract_from_metadata,
    extract_regional_data,
    extract_visible_content,
)
from scraper.parser import extract_json_ld, find_product_json_ld, parse_html
from services.source import SourceService

logger = get_logger(__name__)

# Hard safety cap on products extracted per run.
MAX_PRODUCT_CAP = 100


class ExtractionResult:
    """Structured result of a scraping run."""

    def __init__(self, source_id: str, source_url: str) -> None:
        self.source_id = source_id
        self.source_url = source_url
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None
        self.status = "running"
        self.records_found = 0
        self.records_extracted = 0
        self.records_skipped = 0
        self.records_failed = 0
        self.products: List[Product] = []
        self.errors: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "status": self.status,
            "records_found": self.records_found,
            "records_extracted": self.records_extracted,
            "records_skipped": self.records_skipped,
            "records_failed": self.records_failed,
            "products": [p.model_dump() for p in self.products],
            "errors": self.errors,
        }


class ScrapingRunner:
    """Coordinates extraction for an approved source."""

    def __init__(
        self,
        source_service: Optional[SourceService] = None,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        self.source_service = source_service or SourceService()
        self.http_client = http_client or HttpClient()

    def run(
        self,
        source_id: str,
        start_url: str,
        max_records: int = 100,
    ) -> ExtractionResult:
        """Execute extraction for a source.

        Source authorization is validated before any network access.
        """
        result = ExtractionResult(source_id=source_id, source_url=start_url)

        # ---- Source validation BEFORE any network access ----
        source = self.source_service.get_source_by_id(source_id)
        if not source:
            result.status = "failed"
            result.errors.append(f"Source {source_id} not found")
            result.completed_at = datetime.now(timezone.utc)
            return result

        if not SourceService.is_eligible_for_extraction(source):
            result.status = "rejected"
            result.errors.append(
                f"Source {source_id} is not eligible for extraction "
                f"(authorization_status={source.get('authorization_status')}, "
                f"enabled={source.get('enabled')})"
            )
            result.completed_at = datetime.now(timezone.utc)
            return result

        source_domain = urlparse(source["source_url"]).hostname or ""
        source_type = (source.get("source_type") or "website").lower()
        data_origin = (
            "authorized_api" if source_type == "api" else "approved_public_source"
        )

        # ---- SSRF guard on the starting URL before any network access ----
        start_hostname = urlparse(start_url).hostname or ""
        if _is_private_ip(start_hostname):
            result.status = "failed"
            result.errors.append(
                f"SSRF: private/reserved IP destination rejected: {start_url}"
            )
            result.completed_at = datetime.now(timezone.utc)
            return result

        try:
            self._extract_catalogue(
                result, start_url, source_domain, max_records, data_origin
            )
        except ScrapingError as exc:
            logger.exception("Scraping failed for source %s", source_id)
            result.status = "failed"
            result.errors.append(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error during extraction")
            result.status = "failed"
            result.errors.append(f"Unexpected error: {exc}")
        finally:
            result.completed_at = datetime.now(timezone.utc)
            if result.status == "running":
                result.status = "completed"

        return result

    def _extract_catalogue(
        self,
        result: ExtractionResult,
        start_url: str,
        source_domain: str,
        max_records: int,
        data_origin: str,
    ) -> None:
        """Crawl the catalogue and extract products up to max_records."""
        max_records = max(1, min(max_records, MAX_PRODUCT_CAP))
        visited: set = set()
        queue: List[str] = [start_url]
        pages_crawled = 0

        while queue and result.records_extracted < max_records:
            # Avoid infinite pagination: cap total pages crawled.
            if pages_crawled >= max_records:
                result.errors.append("Page limit reached; stopping pagination.")
                break

            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            parsed = urlparse(url)
            hostname = parsed.hostname or ""

            # SSRF guard: reject private/reserved IP destinations.
            if _is_private_ip(hostname):
                result.records_failed += 1
                result.errors.append(
                    f"SSRF: private/reserved IP destination rejected: {url}"
                )
                continue

            # Domain restriction: skip off-domain URLs.
            if hostname and hostname.lower() != source_domain:
                result.records_skipped += 1
                result.errors.append(f"Skipped off-domain URL: {url}")
                continue

            # If this is the starting URL and it cannot be accessed, fail the run.
            is_start_url = url == start_url

            pages_crawled += 1

            try:
                response = self.http_client.get(url, allowed_domain=source_domain)
            except SourceAccessError as exc:
                result.records_failed += 1
                result.errors.append(f"Access failed for {url}: {exc}")
                if is_start_url:
                    result.status = "failed"
                    return
                continue

            try:
                soup = parse_html(response.text)
            except ParsingError as exc:
                result.records_failed += 1
                result.errors.append(f"Parse failed for {url}: {exc}")
                continue

            extracted = self._extract_products_from_page(
                soup, response.url, result, data_origin
            )
            result.records_found += extracted

            # Discover pagination links (same domain only); off-domain URLs
            # are counted as skipped rather than silently dropped.
            for link in soup.find_all("a", href=True):
                if result.records_extracted >= max_records:
                    break
                href = link.get("href")
                if not href:
                    continue
                next_url = urljoin(response.url, href)
                next_hostname = urlparse(next_url).hostname or ""
                if next_hostname and next_hostname.lower() != source_domain:
                    if next_url not in visited:
                        visited.add(next_url)
                        result.records_skipped += 1
                        result.errors.append(f"Skipped off-domain URL: {next_url}")
                    continue
                if next_url not in visited and next_url not in queue:
                    queue.append(next_url)

    def _extract_products_from_page(
        self,
        soup,
        page_url: str,
        result: ExtractionResult,
        data_origin: str,
    ) -> int:
        """Extract products from a single page. Returns count found on page."""
        found_on_page = 0
        json_ld = extract_json_ld(soup)
        products_json = find_product_json_ld(json_ld)

        if products_json:
            for pj in products_json:
                if result.records_extracted >= MAX_PRODUCT_CAP:
                    break
                try:
                    data = extract_from_json_ld(pj, base_url=page_url)
                    product = build_product(
                        data, result.source_id, result.source_url, data_origin
                    )
                    result.products.append(product)
                    result.records_extracted += 1
                    found_on_page += 1
                except ExtractionError as exc:
                    result.records_skipped += 1
                    result.errors.append(f"Skipped product on {page_url}: {exc}")
                except Exception as exc:  # noqa: BLE001
                    result.records_failed += 1
                    result.errors.append(f"Failed product on {page_url}: {exc}")
        else:
            # Fallback to metadata + visible content extraction.
            try:
                data: dict = {}
                data.update(extract_from_metadata(soup, base_url=page_url))
                data.update(extract_visible_content(soup, base_url=page_url))
                data["product_url"] = data.get("product_url") or page_url
                product = build_product(
                    data, result.source_id, result.source_url, data_origin
                )
                result.products.append(product)
                result.records_extracted += 1
                found_on_page += 1
            except ExtractionError as exc:
                result.records_skipped += 1
                result.errors.append(f"Skipped product on {page_url}: {exc}")
            except Exception as exc:  # noqa: BLE001
                result.records_failed += 1
                result.errors.append(f"Failed product on {page_url}: {exc}")

        return found_on_page
