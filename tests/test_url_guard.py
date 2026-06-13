"""SSRF guard tests for src.fal._http.validate_fetch_url.

Blocklist approach: public hostnames pass; private/loopback/link-local/etc.
IP literals are rejected, as is the `localhost` hostname and non-http(s)
schemes. DNS resolution is intentionally not performed (DNS-rebinding is out
of scope for this local-tool threat model).
"""

from __future__ import annotations

import pytest

from src.fal._http import validate_fetch_url


@pytest.mark.parametrize(
    "url",
    [
        "https://v3.fal.media/files/penguin/x.mp4",
        "https://anything.fal.ai/path/to/file.png",
        "http://cdn.example.com/asset.webp",
        "https://fal.run/result/123",
    ],
)
def test_validate_fetch_url_accepts_public_urls(url):
    validate_fetch_url(url)  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:8188/x",  # loopback
        "http://10.0.0.5/x",  # private
        "http://192.168.1.1/admin",  # private
        "http://[::1]/x",  # IPv6 loopback
        "http://0.0.0.0/x",  # unspecified
        "https://localhost/x",  # loopback hostname
        "http://localhost.localdomain/x",  # loopback hostname alias
        "file:///etc/passwd",  # non-http scheme
        "gopher://127.0.0.1/x",  # non-http scheme
    ],
)
def test_validate_fetch_url_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_fetch_url(url)
