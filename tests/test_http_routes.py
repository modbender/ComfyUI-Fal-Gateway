"""End-to-end aiohttp tests for the four /fal_gateway/* routes.

These hit the actual route handlers (not just pure helpers like
`decode_model_id_b64`), so wiring regressions surface immediately. The
fixture builds a fresh `web.RouteTableDef`, runs `register_routes()` on
it, mounts onto a `TestServer`, and lets `TestClient` issue HTTP requests.

This is the safety net for the upcoming src/ reorg: if a file move breaks
how routes are registered or what they import, these tests fail.
"""

from __future__ import annotations

import base64

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src import model_registry
from src.storage import catalog as catalog_cache, pricing as pricing_cache
from src.routes import register_routes
from src.widget_spec import ModelEntry, WidgetSpec


# ---- fixtures ---------------------------------------------------------


@pytest.fixture
def fake_entry() -> ModelEntry:
    return ModelEntry(
        id="fal-ai/flux/dev",
        display_name="FLUX dev",
        category="text-to-image",
        shape="text_only",
        widgets=[WidgetSpec(name="prompt", kind="STRING", required=True, multiline=True)],
    )


@pytest.fixture
async def client(monkeypatch, fake_entry, tmp_path):
    """Build an isolated aiohttp app + test client per test.

    Routes register against a fresh RouteTableDef so tests don't pollute
    each other.
    """
    # Isolate caches so tests don't read/write the real cache/ folder.
    monkeypatch.setattr(catalog_cache, "CACHE_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(pricing_cache, "_CACHE_PATH", tmp_path / "pricing.json")
    pricing_cache._reset_for_testing()

    # Stub the registry so routes don't try to fetch fal's live catalog.
    monkeypatch.setattr(model_registry, "_models", [fake_entry])
    monkeypatch.setattr(model_registry, "all_models", lambda: [fake_entry])
    monkeypatch.setattr(model_registry, "resolve", lambda v: fake_entry if "flux" in v else None)
    monkeypatch.setattr(model_registry, "reload", lambda: None)

    routes = web.RouteTableDef()
    register_routes(routes)
    app = web.Application()
    app.add_routes(routes)

    async with TestClient(TestServer(app)) as c:
        yield c


def _b64(model_id: str) -> str:
    """JS-style URL-safe base64 with padding stripped — matches the frontend."""
    return base64.urlsafe_b64encode(model_id.encode("utf-8")).decode("ascii").rstrip("=")


# ---- /fal_gateway/schema/{id} -----------------------------------------


async def test_schema_route_returns_model_payload(client, fake_entry):
    res = await client.get(f"/fal_gateway/schema/{_b64(fake_entry.id)}")
    assert res.status == 200
    body = await res.json()
    assert body["ok"] is True
    assert body["model_id"] == fake_entry.id
    assert body["display_name"] == fake_entry.display_name
    assert body["category"] == fake_entry.category
    assert body["shape"] == fake_entry.shape
    assert body["widgets"][0]["name"] == "prompt"
    # Pricing keys always present (None when unknown).
    for k in ("unit_price", "unit", "currency"):
        assert k in body


async def test_schema_route_404_for_unknown_model(client):
    res = await client.get(f"/fal_gateway/schema/{_b64('fal-ai/does-not-exist')}")
    assert res.status == 404
    body = await res.json()
    assert body["ok"] is False
    assert "unknown model_id" in body["error"]


async def test_schema_route_400_for_invalid_base64(client):
    """Malformed base64 path returns 400, not 500."""
    res = await client.get("/fal_gateway/schema/not!valid@base64*chars")
    assert res.status == 400
    body = await res.json()
    assert body["ok"] is False


async def test_schema_route_includes_pricing_when_cached(client, fake_entry, monkeypatch):
    """When pricing_cache has data for this id, the response surfaces it."""
    monkeypatch.setattr(
        pricing_cache,
        "get_for_response",
        lambda eid: {"unit_price": 0.025, "unit": "image", "currency": "USD"},
    )
    res = await client.get(f"/fal_gateway/schema/{_b64(fake_entry.id)}")
    body = await res.json()
    assert body["unit_price"] == 0.025
    assert body["unit"] == "image"
    assert body["currency"] == "USD"


# ---- /fal_gateway/health ----------------------------------------------


async def test_health_route_reports_key_state_and_count(client, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "test-key-123")
    res = await client.get("/fal_gateway/health")
    assert res.status == 200
    body = await res.json()
    assert body["fal_key_present"] is True
    assert body["model_count"] == 1


async def test_health_route_reports_no_key_when_unset(client, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    res = await client.get("/fal_gateway/health")
    body = await res.json()
    assert body["fal_key_present"] is False


# ---- /fal_gateway/refresh ---------------------------------------------


async def test_refresh_route_returns_ok_when_cache_absent(client):
    """Idempotent: refresh against an empty cache succeeds + reports deleted=False."""
    res = await client.post("/fal_gateway/refresh")
    assert res.status == 200
    body = await res.json()
    assert body["ok"] is True
    assert body["deleted"] is False
    assert "Cache cleared" in body["message"] or "background" in body["message"]


async def test_refresh_route_deletes_existing_cache(client, monkeypatch, tmp_path):
    """When a cache file is present, refresh removes it and reports deleted=True."""
    cache_path = tmp_path / "catalog.json"
    cache_path.write_text("{}")
    monkeypatch.setattr(catalog_cache, "CACHE_PATH", cache_path)
    res = await client.post("/fal_gateway/refresh")
    body = await res.json()
    assert body["ok"] is True
    assert body["deleted"] is True
    assert not cache_path.exists()


# ---- /fal_gateway/pricing_refresh -------------------------------------


async def test_pricing_refresh_clears_cache_and_triggers_refetch(client, monkeypatch):
    """Manual pricing refresh clears state and kicks off a background fetch."""
    triggered = []

    def fake_trigger(ids):
        triggered.append(ids)
        return True

    monkeypatch.setattr(pricing_cache, "trigger_refresh_if_stale", fake_trigger)

    res = await client.post("/fal_gateway/pricing_refresh")
    assert res.status == 200
    body = await res.json()
    assert body["ok"] is True
    assert body["started"] is True
    assert "Pricing cache cleared" in body["message"]
    assert len(triggered) == 1
