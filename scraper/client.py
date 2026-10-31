"""HTTP client for the GRANIT EU scraper.

Provides a reusable session-based HTTP client with:

* Configurable request timeout and User-Agent
* HTTP status handling
* SSRF protection (private, loopback and link-local IP rejection)
* Redirect domain restriction (redirects to unapproved domains are not followed)
* Conservative request intervals between requests (no parallelism)

No CAPTCHA, authentication or rate-limit bypassing is performed.
"""

import ipaddress
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings
from core.logging import get_logger
from scraper.exceptions import SourceAccessError

logger = get_logger(__name__)

# Private / reserved IP ranges that must never be requested (SSRF protection).
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def _is_private_ip(host: str) -> bool:
    """Return True when the host is a private/reserved IP address."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname: IP cannot be determined without a DNS lookup. Allow but
        # the domain restriction check still applies at the caller.
        return False
    return any(ip in net for net in _PRIVATE_NETWORKS)


class HttpClient:
    """Reusable HTTP client with safety guards."""

    def __init__(
        self,
        timeout: Optional[int] = None,
        user_agent: Optional[str] = None,
        min_interval: float = 1.0,
    ) -> None:
        self.timeout = timeout or settings.http_request_timeout
        self.user_agent = user_agent or "GRANIT-EU-Scraper/1.0"
        self._min_interval = max(min_interval, 0.0)
        self._last_request_time = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _enforce_interval(self) -> None:
        """Apply a conservative interval between requests (no parallelism)."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _validate_url(self, url: str, allowed_domain: Optional[str] = None) -> str:
        """Validate a URL for scheme, SSRF and domain restrictions."""
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            raise SourceAccessError(f"Unsupported URL scheme: {parsed.scheme!r}")
        if not parsed.netloc:
            raise SourceAccessError(f"Invalid URL (no host): {url!r}")
        hostname = parsed.hostname or ""
        if _is_private_ip(hostname):
            raise SourceAccessError(f"Private/reserved IP destination rejected: {url!r}")
        if allowed_domain and hostname and hostname.lower() != allowed_domain.lower():
            raise SourceAccessError(
                f"URL domain {hostname!r} does not match approved source domain "
                f"{allowed_domain!r}"
            )
        return url.strip()

    def get(
        self,
        url: str,
        allowed_domain: Optional[str] = None,
    ) -> requests.Response:
        """Perform a GET request with safety guards.

        Redirects are not followed (``allow_redirects=False``) so that the
        client never follows a redirect to an unapproved domain.
        """
        validated_url = self._validate_url(url, allowed_domain=allowed_domain)
        self._enforce_interval()
        try:
            response = self.session.get(
                validated_url,
                timeout=self.timeout,
                allow_redirects=False,
            )
            self._last_request_time = time.monotonic()
            response.raise_for_status()
            return response
        except requests.exceptions.SSLError as exc:
            raise SourceAccessError(f"SSL error for {url}: {exc}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise SourceAccessError(f"Connection error for {url}: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise SourceAccessError(f"Request timed out for {url}: {exc}") from exc
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            raise SourceAccessError(f"HTTP {status} for {url}: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise SourceAccessError(f"Request failed for {url}: {exc}") from exc
