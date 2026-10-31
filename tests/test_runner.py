"""Tests for the scraping runner (scraper/runner.py).

Uses mocked HTTP responses and a mocked SourceService; no network access
and no live MongoDB server required.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from scraper.runner import ExtractionResult, ScrapingRunner, MAX_PRODUCT_CAP
from scraper.exceptions import SourceAccessError
from services.source import SourceService


def _make_source(**overrides):
    base = {
        "source_id": "src-1",
        "source_name": "Test Source",
        "source_url": "https://example.com",
        "source_type": "website",
        "authorization_status": "approved",
        "enabled": True,
    }
    base.update(overrides)
    return base


def _make_service(source=None):
    service = MagicMock(spec=SourceService)
    service.get_source_by_id.return_value = source
    return service


def _make_response(html, status_code=200, url="https://example.com/"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = html
    resp.url = url

    def raise_for_status():
        if status_code >= 400:
            raise Exception(f"HTTP {status_code}")

    resp.raise_for_status = raise_for_status
    return resp


def _html_with_product(name="Test Product", article="ART-1"):
    return f"""<html><head>
<script type="application/ld+json">
{{"@context": "https://schema.org/", "@type": "Product", "name": "{name}", "sku": "{article}", "brand": {{"name": "TestBrand"}}}}
</script>
</head><body></body></html>"""


def test_source_not_found():
    service = _make_service(None)
    runner = ScrapingRunner(source_service=service)
    result = runner.run("missing", "https://example.com/")
    assert result.status == "failed"
    assert "not found" in result.errors[0]
    assert result.records_extracted == 0


def test_pending_source_rejected():
    service = _make_service(_make_source(authorization_status="pending"))
    runner = ScrapingRunner(source_service=service)
    result = runner.run("src-1", "https://example.com/")
    assert result.status == "rejected"
    assert "not eligible" in result.errors[0]


def test_rejected_source_rejected():
    service = _make_service(_make_source(authorization_status="rejected"))
    runner = ScrapingRunner(source_service=service)
    result = runner.run("src-1", "https://example.com/")
    assert result.status == "rejected"


def test_disabled_source_rejected():
    service = _make_service(_make_source(authorization_status="approved", enabled=False))
    runner = ScrapingRunner(source_service=service)
    result = runner.run("src-1", "https://example.com/")
    assert result.status == "rejected"


def test_no_network_access_for_unauthorized_source():
    service = _make_service(_make_source(authorization_status="pending"))
    runner = ScrapingRunner(source_service=service)
    with patch("requests.Session.get") as mock_get:
        runner.run("src-1", "https://example.com/")
        mock_get.assert_not_called()


def test_successful_extraction():
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    html = _html_with_product()
    with patch("requests.Session.get") as mock_get:
        mock_get.return_value = _make_response(html)
        result = runner.run("src-1", "https://example.com/product/1")
    assert result.status == "completed"
    assert result.records_extracted == 1
    assert result.records_found == 1
    assert result.products[0].product_name == "Test Product"
    assert result.products[0].data_origin == "approved_public_source"
    assert result.products[0].is_synthetic is False
    assert result.products[0].verification_status == "not_verified"


def test_api_source_uses_authorized_api_origin():
    service = _make_service(
        _make_source(source_type="api", source_url="https://api.example.com")
    )
    runner = ScrapingRunner(source_service=service)
    html = _html_with_product()
    with patch("requests.Session.get") as mock_get:
        mock_get.return_value = _make_response(html)
        result = runner.run("src-1", "https://api.example.com/product/1")
    assert result.products[0].data_origin == "authorized_api"


def test_http_403_handled():
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    with patch("requests.Session.get") as mock_get:
        mock_get.return_value = _make_response("<html></html>", status_code=403)
        result = runner.run("src-1", "https://example.com/product/1")
    assert result.status == "failed"
    assert any("HTTP 403" in e for e in result.errors)


def test_timeout_handled():
    import requests
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    with patch("requests.Session.get") as mock_get:
        mock_get.side_effect = requests.exceptions.Timeout("timed out")
        result = runner.run("src-1", "https://example.com/product/1")
    assert result.status == "failed"
    assert any("timed out" in e for e in result.errors)


def test_max_records_limit_enforced():
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    html = _html_with_product()
    with patch("requests.Session.get") as mock_get:
        mock_get.return_value = _make_response(html)
        result = runner.run("src-1", "https://example.com/", max_records=3)
    assert result.records_extracted <= 3


def test_ssrf_start_url_rejected():
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    result = runner.run("src-1", "http://127.0.0.1/local")
    assert result.status == "failed"
    assert any("private/reserved IP" in e for e in result.errors)


def test_off_domain_url_skipped():
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    # Start page links to an off-domain URL.
    html = """<html><body><a href="https://evil.com/product">Evil</a></body></html>"""
    with patch("requests.Session.get") as mock_get:
        mock_get.return_value = _make_response(html)
        result = runner.run("src-1", "https://example.com/", max_records=5)
    assert any("off-domain" in e for e in result.errors)
    assert result.records_skipped >= 1


def test_pagination_loop_prevention():
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    page_a = """<html><body><a href="https://example.com/page-b">Page B</a></body></html>"""
    page_b = """<html><body><a href="https://example.com/page-a">Page A</a></body></html>"""
    responses = {
        "https://example.com/": page_a,
        "https://example.com/page-b": page_b,
    }

    def fake_get(url, **kwargs):
        return _make_response(responses.get(url, "<html></html>"), url=url)

    with patch("requests.Session.get") as mock_get:
        mock_get.side_effect = fake_get
        result = runner.run("src-1", "https://example.com/", max_records=10)
    # Should terminate without infinite looping.
    assert result.status in ("completed", "failed")
    # Page A and Page B each crawled once.
    assert mock_get.call_count <= 3


def test_duplicate_url_not_reprocessed():
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    html = _html_with_product()
    with patch("requests.Session.get") as mock_get:
        mock_get.return_value = _make_response(html)
        # Same URL appears via queue; visited set dedupes.
        result = runner.run("src-1", "https://example.com/product/1", max_records=5)
    assert result.records_extracted == 1


def test_extraction_result_structure():
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    html = _html_with_product()
    with patch("requests.Session.get") as mock_get:
        mock_get.return_value = _make_response(html)
        result = runner.run("src-1", "https://example.com/product/1")
    d = result.to_dict()
    for key in (
        "source_id", "source_url", "started_at", "completed_at", "status",
        "records_found", "records_extracted", "records_skipped",
        "records_failed", "products", "errors",
    ):
        assert key in d, f"Missing key {key}"
    assert d["source_id"] == "src-1"
    assert len(d["products"]) == 1
    assert d["products"][0]["product_name"] == "Test Product"


def test_hard_cap_respected():
    service = _make_service(_make_source())
    runner = ScrapingRunner(source_service=service)
    html = _html_with_product()
    with patch("requests.Session.get") as mock_get:
        mock_get.return_value = _make_response(html)
        # Request more than the hard cap.
        result = runner.run("src-1", "https://example.com/", max_records=500)
    assert result.records_extracted <= MAX_PRODUCT_CAP
