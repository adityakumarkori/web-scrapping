"""Tests for the HTTP client (scraper/client.py).

Tests SSRF protection, redirect handling, scheme validation, and error
handling. No network access is performed; requests.Session.get is mocked.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper.client import HttpClient, _is_private_ip
from scraper.exceptions import SourceAccessError


def _make_response(status_code=200):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code

    def raise_for_status():
        if status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"HTTP {status_code}", response=resp
            )

    resp.raise_for_status = raise_for_status
    return resp


def test_private_ip_rejected():
    assert _is_private_ip("127.0.0.1") is True
    assert _is_private_ip("10.0.0.1") is True
    assert _is_private_ip("192.168.1.1") is True
    assert _is_private_ip("172.16.0.1") is True
    assert _is_private_ip("169.254.169.254") is True
    assert _is_private_ip("::1") is True
    assert _is_private_ip("fc00::1") is True
    assert _is_private_ip("8.8.8.8") is False
    assert _is_private_ip("example.com") is False  # hostname cannot be resolved


def test_unsupported_scheme_rejected():
    client = HttpClient()
    with pytest.raises(SourceAccessError):
        client._validate_url("ftp://example.com")


def test_no_host_rejected():
    client = HttpClient()
    with pytest.raises(SourceAccessError):
        client._validate_url("http://")


def test_private_ip_destination_rejected():
    client = HttpClient()
    with pytest.raises(SourceAccessError):
        client._validate_url("http://127.0.0.1/local")
    with pytest.raises(SourceAccessError):
        client._validate_url("http://169.254.169.254/")


def test_domain_mismatch_rejected():
    client = HttpClient()
    with pytest.raises(SourceAccessError):
        client._validate_url("http://evil.com/", allowed_domain="example.com")


def test_valid_url_passes():
    client = HttpClient()
    assert client._validate_url("https://example.com/", allowed_domain="example.com") == "https://example.com/"


@patch("requests.Session.get")
def test_successful_get(mock_get):
    mock_get.return_value = _make_response(200)
    client = HttpClient()
    resp = client.get("https://example.com/", allowed_domain="example.com")
    assert resp.status_code == 200
    mock_get.assert_called_once()
    kwargs = mock_get.call_args.kwargs
    assert kwargs["allow_redirects"] is False
    assert "timeout" in kwargs


@patch("requests.Session.get")
def test_http_403_raises(mock_get):
    mock_get.return_value = _make_response(403)
    client = HttpClient()
    with pytest.raises(SourceAccessError, match="HTTP 403"):
        client.get("https://example.com/", allowed_domain="example.com")


@patch("requests.Session.get")
def test_http_404_raises(mock_get):
    mock_get.return_value = _make_response(404)
    client = HttpClient()
    with pytest.raises(SourceAccessError, match="HTTP 404"):
        client.get("https://example.com/", allowed_domain="example.com")


@patch("requests.Session.get")
def test_timeout_raises(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout("timed out")
    client = HttpClient()
    with pytest.raises(SourceAccessError, match="timed out"):
        client.get("https://example.com/", allowed_domain="example.com")


@patch("requests.Session.get")
def test_connection_error_raises(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("refused")
    client = HttpClient()
    with pytest.raises(SourceAccessError, match="Connection error"):
        client.get("https://example.com/", allowed_domain="example.com")


@patch("requests.Session.get")
def test_redirect_not_followed(mock_get):
    # allow_redirects=False means a 3xx response is returned, not followed.
    resp = _make_response(302)
    mock_get.return_value = resp
    client = HttpClient()
    result = client.get("https://example.com/old", allowed_domain="example.com")
    assert result.status_code == 302
    assert mock_get.call_args.kwargs["allow_redirects"] is False


@patch("requests.Session.get")
def test_off_domain_blocked_before_request(mock_get):
    client = HttpClient()
    with pytest.raises(SourceAccessError, match="does not match approved source domain"):
        client.get("https://evil.com/", allowed_domain="example.com")
    mock_get.assert_not_called()
