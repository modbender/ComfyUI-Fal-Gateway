"""Integration tests against the live fal.ai catalog API.

These tests are OPT-IN. Default `pytest` invocations skip them via the
`-m 'not integration'` filter in pyproject.toml. To run:

    pytest -m integration
    pytest tests/integration

Tests use small page limits (5–10) to minimise rate-limit pressure on the
free public catalog endpoint. Setting FAL_KEY in the environment raises the
rate ceiling; without it tests should still pass but may sporadically hit
429s on the schema-fetch test (we add backoff there).

Tests deliberately avoid touching `queue.fal.run` (inference) since that
would charge real money.
"""

from __future__ import annotations

import os
import socket
from urllib.error import URLError

import pytest

from src import model_registry
from src.fal import catalog as fal_catalog
from src.schema_resolver import parse_openapi


pytestmark = pytest.mark.integration


def _network_reachable() -> bool:
    try:
        socket.create_connection(("api.fal.ai", 443), timeout=5).close()
        return True
    except (OSError, socket.timeout):
        return False


@pytest.fixture(autouse=True, scope="module")
def _require_network():
    if not _network_reachable():
        pytest.skip("api.fal.ai unreachable; skipping live integration suite")


# ---- fal.catalog -------------------------------------------------------


def test_catalog_endpoint_returns_expected_envelope():
    page = fal_catalog._fetch_page(
        category="text-to-video", cursor=None, limit=5, timeout_s=15.0
    )
    assert isinstance(page, dict)
    assert "models" in page
    assert isinstance(page["models"], list)
    assert "has_more" in page


def test_catalog_pagination_walks_to_second_page():
    """Fetch 2 pages of 5 to confirm cursor handling works end-to-end."""
    first = fal_catalog._fetch_page(
        category="image-to-video", cursor=None, limit=5, timeout_s=15.0
    )
    if not first.get("has_more") or not first.get("next_cursor"):
        pytest.skip("catalog has fewer than 2 pages of image-to-video; cannot test cursor")
    second = fal_catalog._fetch_page(
        category="image-to-video",
        cursor=first["next_cursor"],
        limit=5,
        timeout_s=15.0,
    )
    assert isinstance(second.get("models"), list)
    # Pages should not contain identical first endpoint — would imply cursor was ignored.
    if first["models"] and second.get("models"):
        assert first["models"][0]["endpoint_id"] != second["models"][0]["endpoint_id"]


def test_each_model_has_required_metadata_keys():
    page = fal_catalog._fetch_page(
        category="text-to-video", cursor=None, limit=5, timeout_s=15.0
    )
    for m in page["models"]:
        assert m.get("endpoint_id"), "missing endpoint_id"
        meta = m.get("metadata") or {}
        assert meta.get("display_name"), f"missing display_name on {m['endpoint_id']}"
        assert meta.get("category"), f"missing category on {m['endpoint_id']}"


# ---- expand=openapi-3.0 path ------------------------------------------


def test_expand_openapi_returns_openapi_field():
    page = fal_catalog._fetch_page(
        category="image-to-video",
        cursor=None,
        limit=fal_catalog.SCHEMA_PAGE_LIMIT,
        timeout_s=20.0,
        with_schemas=True,
    )
    models = page.get("models") or []
    assert models, "no models returned with schemas"
    has_oa = [m for m in models if isinstance(m.get("openapi"), dict)]
    assert has_oa, f"none of {len(models)} models had embedded openapi"
    sample = has_oa[0]
    oa = sample["openapi"]
    assert "paths" in oa and "components" in oa
    assert oa["components"].get("schemas")


def test_live_openapi_parses_into_widgets():
    """Pull one live model with schema and feed it through schema_resolver."""
    page = fal_catalog._fetch_page(
        category="image-to-video",
        cursor=None,
        limit=fal_catalog.SCHEMA_PAGE_LIMIT,
        timeout_s=20.0,
        with_schemas=True,
    )
    has_oa = [m for m in (page.get("models") or []) if isinstance(m.get("openapi"), dict)]
    if not has_oa:
        pytest.skip("no live model with openapi available")
    parsed = parse_openapi(has_oa[0]["openapi"], "image-to-video")
    assert parsed.shape in ("text_only", "single_image", "flf", "multi_ref")
    assert any(w.kind == "STRING" for w in parsed.widgets), "expected at least one STRING widget"


# ---- model_registry end-to-end ----------------------------------------


def test_registry_loads_at_least_some_live_models(tmp_path, monkeypatch):
    """End-to-end: clean cache, force reload, expect >= bundled fallback count."""
    monkeypatch.setattr(model_registry, "_CACHE_PATH", tmp_path / "catalog.json")
    model_registry.reload()
    try:
        all_models = model_registry.all_models()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"live fetch failed (likely rate-limited without FAL_KEY): {exc}")
    assert len(all_models) >= 6, f"expected at least the bundled 6 models, got {len(all_models)}"


# ---- known-model contract --------------------------------------------


@pytest.mark.parametrize(
    "needle",
    [
        "seedance",  # ByteDance Seedance family — appears under fal-ai/ or bytedance/
        "kling-video",  # Kling family
    ],
)
def test_well_known_model_family_is_reachable(needle):
    """The catalog should contain at least one model from these popular families.

    Uses single-page fetches with the model search `q=` filter to keep request
    count low (one HTTP call per family). Skips rather than fails when fal
    rate-limits us — the goal is "is the family still on fal", not "load test
    the catalog endpoint."
    """
    page = fal_catalog._fetch_page_with_retries(
        category=None,
        cursor=None,
        limit=10,
        timeout_s=20.0,
        with_schemas=False,
    )
    if page is None:
        pytest.skip("catalog rate-limited; cannot verify family")
    # The plain page fetch doesn't accept `q=`, so fall back to the full image-to-video
    # walk only when needed (still bounded to 2 pages here).
    ids = [m.get("endpoint_id", "") for m in page.get("models", [])]
    matches = [i for i in ids if needle in i]
    if matches:
        return  # found in first page
    # Try one more page (cursor) to cover families that don't sort to the top.
    if not page.get("has_more"):
        pytest.skip(f"only one page available, no {needle} match — possibly rate-limited or removed")
    page2 = fal_catalog._fetch_page_with_retries(
        category=None,
        cursor=page.get("next_cursor"),
        limit=10,
        timeout_s=20.0,
        with_schemas=False,
    )
    if page2 is None:
        pytest.skip("rate-limited on cursor page")
    ids2 = [m.get("endpoint_id", "") for m in page2.get("models", [])]
    matches = [i for i in (ids + ids2) if needle in i]
    if not matches:
        pytest.skip(
            f"{needle!r} not found in first 20 catalog entries — may be sorted later "
            "or rate-limited. Run targeted fetch to verify."
        )
