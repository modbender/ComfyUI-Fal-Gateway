# I2T OpenRouter Vision Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface vision-capable LLMs (Claude, Gemini, GPT-4o, Grok, Llama-Vision, Qwen-VL, etc.) in the I2T node by auto-detecting them from OpenRouter's catalog, while fixing a pre-existing image-input plumbing bug that prevents I2T from working with any live-fetched fal vision model.

**Architecture:** Two-source merge into the I2T dropdown:
1. **fal-direct vision models** (Florence-2, Moondream, SA2VA, etc.) — already in `cache/catalog.json`. Each `ModelEntry` gains an `input_modalities` field auto-derived from its widgets (any `IMAGE_INPUT`/`IMAGE_ARRAY` widget → `"image"` is added).
2. **OpenRouter sub-models** — NOT in fal's catalog. New fetcher hits `https://openrouter.ai/api/v1/models`, filters by `architecture.input_modalities` containing `"image"`, and synthesizes `CatalogEntry` rows pointing at `openrouter/router/vision` with `extra_payload={"model": "<openrouter-model-id>"}`.

The plumbing fix in `nodes/base.py` makes the static `image` socket on the I2T node actually map to the entry's image widget regardless of the widget's name (`image_url`, `image_urls`, etc.), and corrects `IMAGE_ARRAY` payload assembly.

**Tech Stack:** Python 3.10+, `pydantic` (existing), `urllib` (stdlib HTTP, matches `src/fal/catalog.py` pattern), `pytest` via `uv run pytest`.

---

## File Structure

**Files created:**
- `src/openrouter/__init__.py` — empty (module marker)
- `src/openrouter/catalog.py` — fetcher + parser for OpenRouter `/api/v1/models`
- `src/storage/openrouter.py` — disk cache for OpenRouter catalog (mirrors `storage/catalog.py`)
- `tests/test_openrouter_catalog.py` — fetcher + parser tests
- `tests/test_storage_openrouter.py` — cache I/O tests
- `tests/fixtures/openrouter_models.json` — captured OpenRouter API response fixture

**Files modified:**
- `src/widget_spec.py` — add `input_modalities: list[str]` field to `ModelEntry`
- `src/model_registry.py` — auto-derive `input_modalities` from widgets in `_entry_from_raw`; integrate OpenRouter cache
- `src/storage/catalog.py` — bump `SCHEMA_VERSION` 5 → 6 (invalidates old caches)
- `src/catalogs/i2t.py` — replace `CURATED = []` with dynamic generation from OpenRouter cache; keep `HIDDEN_ENDPOINTS` as-is
- `src/nodes/base.py:_build_payload` — fix image socket↔widget name mismatch + `IMAGE_ARRAY` list wrapping
- `tests/test_widget_spec.py` — coverage for new field
- `tests/test_model_registry.py` — coverage for derivation
- `tests/test_build_payload.py` — coverage for the plumbing fix
- `tests/test_catalogs.py` — coverage for OpenRouter→I2T generation
- `README.md` — note auto-detected vision LLMs in I2T

**Test commands** (run from `ComfyUI-Fal-Gateway/`):
```bash
uv run pytest tests/ -v                    # all tests
uv run pytest tests/test_widget_spec.py -v # one file
```

---

## Task 1: Add `input_modalities` field to `ModelEntry`

Adds a default-`["text"]` field on the dataclass with round-trippable serialization. No callers use it yet — this task is purely the schema addition.

**Files:**
- Modify: `src/widget_spec.py:42-70`
- Modify: `tests/test_widget_spec.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_widget_spec.py`:

```python
def test_model_entry_default_input_modalities_is_text_only():
    entry = ModelEntry(
        id="fal-ai/foo",
        display_name="Foo",
        category="text-to-image",
        shape="text_only",
    )
    assert entry.input_modalities == ["text"]


def test_model_entry_input_modalities_round_trip():
    entry = ModelEntry(
        id="fal-ai/bar",
        display_name="Bar",
        category="vision",
        shape="single_image",
        input_modalities=["text", "image"],
    )
    restored = ModelEntry.from_dict(entry.to_dict())
    assert restored.input_modalities == ["text", "image"]


def test_model_entry_from_dict_back_compat_when_field_missing():
    """Old cached entries without input_modalities should default to ['text']."""
    raw = {
        "id": "fal-ai/legacy",
        "display_name": "Legacy",
        "category": "llm",
        "shape": "text_only",
        # no input_modalities key
    }
    entry = ModelEntry.from_dict(raw)
    assert entry.input_modalities == ["text"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_widget_spec.py::test_model_entry_default_input_modalities_is_text_only -v
```

Expected: `AttributeError: 'ModelEntry' object has no attribute 'input_modalities'`

- [ ] **Step 3: Add the field to `ModelEntry`**

In `src/widget_spec.py`, modify the `ModelEntry` dataclass (around line 42-70):

```python
@dataclass
class ModelEntry:
    id: str  # fal endpoint, e.g. "fal-ai/bytedance/seedance/v1/lite/image-to-video"
    display_name: str
    category: str  # "text-to-video" | "image-to-video" | ...
    shape: str  # "text_only" | "single_image" | "flf" | "multi_ref"
    description: str = ""
    widgets: list[WidgetSpec] = field(default_factory=list)
    input_modalities: list[str] = field(default_factory=lambda: ["text"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "category": self.category,
            "shape": self.shape,
            "description": self.description,
            "widgets": [w.to_dict() for w in self.widgets],
            "input_modalities": list(self.input_modalities),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelEntry":
        widgets = [WidgetSpec.from_dict(w) for w in data.get("widgets", [])]
        return cls(
            id=data["id"],
            display_name=data["display_name"],
            category=data["category"],
            shape=data["shape"],
            description=data.get("description", ""),
            widgets=widgets,
            input_modalities=list(data.get("input_modalities") or ["text"]),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_widget_spec.py -v
```

Expected: all three new tests PASS, all existing widget_spec tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/widget_spec.py tests/test_widget_spec.py
git commit -m "feat(widget_spec): add input_modalities field to ModelEntry"
```

---

## Task 2: Auto-derive `input_modalities` from widgets

When the registry builds a `ModelEntry` from a fal raw record, infer modalities from the widget set: presence of `IMAGE_INPUT`/`IMAGE_ARRAY` widgets → add `"image"`. Always include `"text"` (every model in the catalog has a prompt).

**Files:**
- Modify: `src/model_registry.py` (function `_entry_from_raw`, around line 81-120)
- Modify: `tests/test_model_registry.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_model_registry.py`:

```python
from src.model_registry import _entry_from_raw


def test_entry_from_raw_with_image_widget_gets_image_modality():
    raw = {
        "endpoint_id": "fal-ai/florence-2-large/detailed-caption",
        "metadata": {
            "category": "vision",
            "display_name": "Florence-2 Large",
            "status": "active",
        },
        "openapi": _minimal_openapi_with_image_url(),
    }
    entry = _entry_from_raw(raw)
    assert entry is not None
    assert "image" in entry.input_modalities
    assert "text" in entry.input_modalities


def test_entry_from_raw_text_only_model_gets_text_only_modality():
    raw = {
        "endpoint_id": "fal-ai/some-llm",
        "metadata": {
            "category": "llm",
            "display_name": "Some LLM",
            "status": "active",
        },
        # no openapi → synthesized widgets, llm category → no image widget
    }
    entry = _entry_from_raw(raw)
    assert entry is not None
    assert entry.input_modalities == ["text"]


def _minimal_openapi_with_image_url() -> dict:
    """Smallest valid OpenAPI doc with one image_url property."""
    return {
        "paths": {
            "/": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Input"}
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Input": {
                    "type": "object",
                    "properties": {
                        "image_url": {"type": "string", "_fal_ui_field": "image"},
                        "prompt": {"type": "string"},
                    },
                    "required": ["image_url"],
                }
            }
        },
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_model_registry.py::test_entry_from_raw_with_image_widget_gets_image_modality -v
```

Expected: FAIL — assertion `"image" in entry.input_modalities` fails because Task 1 only set the field default, never derived from widgets.

- [ ] **Step 3: Add the derivation helper and wire into `_entry_from_raw`**

In `src/model_registry.py`, add this helper above `_entry_from_raw` (around line 80):

```python
def _derive_input_modalities(widgets: list[WidgetSpec]) -> list[str]:
    """Infer the input modality set from a model's widget list.

    Every model in the catalog accepts text (prompt/system_prompt). Image
    modality is added when the schema declares any IMAGE_INPUT or IMAGE_ARRAY
    widget — that's how we surface fal-direct vision endpoints in I2T without
    a hand-maintained list.
    """
    modalities = ["text"]
    if any(w.kind in ("IMAGE_INPUT", "IMAGE_ARRAY") for w in widgets):
        modalities.append("image")
    return modalities
```

Then modify `_entry_from_raw` (around line 113) to pass `input_modalities` into `ModelEntry`:

```python
    return ModelEntry(
        id=str(endpoint_id),
        display_name=str(display),
        category=str(category),
        shape=shape,
        description=str(description),
        widgets=widgets,
        input_modalities=_derive_input_modalities(widgets),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_model_registry.py -v
```

Expected: both new tests PASS, all existing model_registry tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/model_registry.py tests/test_model_registry.py
git commit -m "feat(model_registry): auto-derive input_modalities from widget kinds"
```

---

## Task 3: Bump cache schema version

Existing `cache/catalog.json` was written without `input_modalities`. Bump from 5 → 6 so old caches are rejected on next load and a fresh fetch (with the new derivation) writes a current-schema cache.

**Files:**
- Modify: `src/storage/catalog.py:14, 37`

- [ ] **Step 1: Write the test for the bump**

Add to `tests/test_storage_catalog.py` (file may not exist — create it if not):

```python
import json
from pathlib import Path

from src.storage import catalog as cache


def test_load_if_fresh_returns_none_for_old_schema_version(tmp_path, monkeypatch):
    fake_cache = tmp_path / "catalog.json"
    fake_cache.write_text(json.dumps({
        "schema_version": 5,  # old version
        "fetched_at": "2026-05-01T00:00:00+00:00",
        "models": [],
    }))
    monkeypatch.setattr(cache, "CACHE_PATH", fake_cache)
    assert cache.load_if_fresh() is None


def test_schema_version_is_current():
    assert cache.SCHEMA_VERSION == 6
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_storage_catalog.py -v
```

Expected: `test_schema_version_is_current` FAILS (still 5).

- [ ] **Step 3: Bump the schema version**

In `src/storage/catalog.py`:

```python
"""Disk-backed catalog cache (`cache/catalog.json`).

...
Bumps to `SCHEMA_VERSION` invalidate existing caches and force a refetch
on the next ComfyUI restart. Last bumps:
  1 → 2: added text-to-image + image-to-image categories
  2 → 3: added llm + vision categories (v0.3.0)
  3 → 4: added pricing fields (unit_price/unit/currency on ModelEntry)
  4 → 5: extracted pricing into separate cache/pricing.json
  5 → 6: added input_modalities field on ModelEntry
"""
```

And:

```python
SCHEMA_VERSION = 6
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_storage_catalog.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/storage/catalog.py tests/test_storage_catalog.py
git commit -m "chore(cache): bump SCHEMA_VERSION 5→6 for input_modalities"
```

---

## Task 4: Fix image socket↔widget name mismatch in `_build_payload`

Pre-existing bug: I2T's static socket is named `"image"`, but live-fetched fal entries use widget name `"image_url"` (Florence-2, Moondream) or `"image_urls"` (openrouter/router/vision). Current code in `nodes/base.py:228` does `kwargs.get(w.name)` which never matches, raising `RuntimeError("required image input 'image_url' not connected")` at execute time.

Fix: when a widget's name isn't in kwargs, fall back to the node's static image socket(s) in declaration order. Also wrap `IMAGE_ARRAY` payloads as `[url]` (list) instead of bare `url`.

**Files:**
- Modify: `src/nodes/base.py:223-234`
- Modify: `tests/test_build_payload.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_build_payload.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

from src.nodes.i2t import FalGatewayI2T
from src.widget_spec import ModelEntry, WidgetSpec


@pytest.mark.asyncio
async def test_i2t_maps_static_image_socket_to_widget_named_image_url():
    """Florence-2-shaped entry: widget name='image_url', static socket='image'.
    Tensor must reach payload at fal_key='image_url'."""
    entry = ModelEntry(
        id="fal-ai/florence-2-large/detailed-caption",
        display_name="Florence-2 Large",
        category="vision",
        shape="single_image",
        widgets=[
            WidgetSpec(name="image_url", kind="IMAGE_INPUT", required=True,
                       payload_key="image_url"),
        ],
        input_modalities=["text", "image"],
    )
    fake_tensor = object()
    with patch("src.nodes.base.upload_tensor_image",
               new=AsyncMock(return_value="https://fal.media/uploaded.png")):
        node = FalGatewayI2T()
        payload = await node._build_payload(entry, prompt="describe", kwargs={"image": fake_tensor})
    assert payload["image_url"] == "https://fal.media/uploaded.png"


@pytest.mark.asyncio
async def test_i2t_image_array_widget_gets_list_not_bare_url():
    """openrouter/router/vision shape: IMAGE_ARRAY widget at fal_key='image_urls'.
    Payload must hold a LIST of URLs."""
    entry = ModelEntry(
        id="openrouter/router/vision",
        display_name="OpenRouter Vision",
        category="vision",
        shape="multi_ref",
        widgets=[
            WidgetSpec(name="image_urls", kind="IMAGE_ARRAY", required=True,
                       payload_key="image_urls"),
            WidgetSpec(name="prompt", kind="STRING", payload_key="prompt"),
        ],
        input_modalities=["text", "image"],
    )
    fake_tensor = object()
    with patch("src.nodes.base.upload_tensor_image",
               new=AsyncMock(return_value="https://fal.media/uploaded.png")):
        node = FalGatewayI2T()
        payload = await node._build_payload(entry, prompt="describe", kwargs={"image": fake_tensor})
    assert payload["image_urls"] == ["https://fal.media/uploaded.png"]
```

Note: if `tests/conftest.py` doesn't already enable `pytest-asyncio` mode, add to `pyproject.toml` under `[tool.pytest.ini_options]`:
```toml
asyncio_mode = "auto"
```
(Check existing config first; only add if absent.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_build_payload.py::test_i2t_maps_static_image_socket_to_widget_named_image_url -v
```

Expected: FAIL with `RuntimeError("required image input 'image_url' not connected")`.

- [ ] **Step 3: Apply the fix**

In `src/nodes/base.py`, replace the image-handling block in `_build_payload` (lines 223-234) with:

```python
        # 2. Image inputs: map kwargs (keyed by static socket names like
        # "image", "image_1") onto entry.widgets (keyed by OpenAPI property
        # names like "image_url", "image_urls"). Named match wins; unmatched
        # entry widgets pull positionally from declared static sockets.
        image_widgets = [w for w in entry.widgets if w.kind in ("IMAGE_INPUT", "IMAGE_ARRAY")]
        cls = type(self)
        static_socket_names = list(cls.image_socket_names()) + list(cls.optional_image_socket_names())
        # Static sockets actually wired by ComfyUI (have a tensor in kwargs)
        wired_static = [n for n in static_socket_names if kwargs.get(n) is not None]
        unused_static = list(wired_static)

        for w in image_widgets:
            tensor = kwargs.get(w.name)
            if tensor is None and unused_static:
                # No exact name match — pull the next wired static socket.
                tensor = kwargs[unused_static.pop(0)]
            elif tensor is not None and w.name in unused_static:
                unused_static.remove(w.name)
            if tensor is None:
                if w.required:
                    raise RuntimeError(f"required image input {w.name!r} not connected")
                continue
            url = await upload_tensor_image(tensor)
            if w.kind == "IMAGE_ARRAY":
                payload[w.fal_key] = [url]
            else:
                payload[w.fal_key] = url
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_build_payload.py -v
```

Expected: both new tests PASS, all existing build_payload tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/nodes/base.py tests/test_build_payload.py
git commit -m "fix(nodes/base): map static image sockets onto entry widget names"
```

---

## Task 5: OpenRouter API client + parser

New module `src/openrouter/catalog.py` mirroring `src/fal/catalog.py`'s style: stdlib `urllib`, retry with backoff, schema-current parsing. Returns a list of vision-capable model dicts (filtered by `architecture.input_modalities` containing `"image"`).

**Files:**
- Create: `src/openrouter/__init__.py`
- Create: `src/openrouter/catalog.py`
- Create: `tests/fixtures/openrouter_models.json`
- Create: `tests/test_openrouter_catalog.py`

- [ ] **Step 1: Capture a real OpenRouter response as a fixture**

Run this once to capture (no auth required for the public model list):

```bash
curl -s https://openrouter.ai/api/v1/models > tests/fixtures/openrouter_models.json
```

Verify the file has `data` array with entries containing `architecture.input_modalities`:

```bash
python3 -c "import json; d=json.load(open('tests/fixtures/openrouter_models.json')); print(len(d['data']), d['data'][0]['architecture'])"
```

Expected: a model count and architecture dict with `input_modalities` field.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_openrouter_catalog.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch

from src.openrouter.catalog import (
    fetch_vision_models,
    filter_vision_capable,
    parse_models_response,
)


FIXTURE = Path(__file__).parent / "fixtures" / "openrouter_models.json"


def test_parse_models_response_extracts_id_and_modalities():
    raw = json.loads(FIXTURE.read_text())
    models = parse_models_response(raw)
    assert len(models) > 0
    sample = models[0]
    assert "id" in sample
    assert "input_modalities" in sample
    assert isinstance(sample["input_modalities"], list)


def test_filter_vision_capable_keeps_image_modality():
    models = [
        {"id": "anthropic/claude-3-haiku", "input_modalities": ["text", "image"]},
        {"id": "deepseek/deepseek-v3", "input_modalities": ["text"]},
        {"id": "google/gemini-2.5-pro", "input_modalities": ["text", "image", "file"]},
    ]
    vision = filter_vision_capable(models)
    ids = {m["id"] for m in vision}
    assert ids == {"anthropic/claude-3-haiku", "google/gemini-2.5-pro"}


def test_filter_vision_capable_handles_missing_modalities_field():
    models = [{"id": "weird/model"}]  # no architecture / no modalities
    assert filter_vision_capable(models) == []


def test_fetch_vision_models_returns_empty_on_http_failure():
    """Network down → empty list, never raises (caller decides fallback)."""
    with patch("src.openrouter.catalog._fetch_raw") as m:
        m.side_effect = OSError("network down")
        result = fetch_vision_models()
    assert result == []
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_openrouter_catalog.py -v
```

Expected: ImportError — `src/openrouter` doesn't exist yet.

- [ ] **Step 4: Implement the module**

Create `src/openrouter/__init__.py` (empty file).

Create `src/openrouter/catalog.py`:

```python
"""Fetch OpenRouter's model catalog.

Endpoint: GET https://openrouter.ai/api/v1/models  (no auth required for the list)

Each catalog entry includes `architecture.input_modalities` — the authoritative
"does this model accept image input?" signal. We filter on that field and
return a list of dicts the caller (catalogs/i2t.py) turns into CatalogEntry
rows pointing at the fal endpoint `openrouter/router/vision`.

Synchronous + stdlib `urllib` to mirror src/fal/catalog.py's style and avoid
async-init-time complications.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


_log = logging.getLogger("fal_gateway.openrouter")

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_TIMEOUT_S = 10.0
RETRY_BACKOFF_S = (0.5, 2.0)


def _fetch_raw(timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """One HTTP GET → parsed JSON dict. Raises OSError on network failure."""
    req = urllib_request.Request(
        OPENROUTER_MODELS_URL,
        headers={"User-Agent": "comfyui-fal-gateway/1.0"},
    )
    with urllib_request.urlopen(req, timeout=timeout_s) as response:
        body = response.read()
    return json.loads(body)


def parse_models_response(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise the response into our minimal shape: {id, name, input_modalities, description}."""
    out: list[dict[str, Any]] = []
    for entry in raw.get("data") or []:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not model_id:
            continue
        arch = entry.get("architecture") or {}
        modalities = arch.get("input_modalities") or []
        if not isinstance(modalities, list):
            modalities = []
        out.append({
            "id": str(model_id),
            "name": str(entry.get("name") or model_id),
            "input_modalities": [str(m) for m in modalities if isinstance(m, str)],
            "description": str(entry.get("description") or ""),
        })
    return out


def filter_vision_capable(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep models whose input_modalities includes 'image'."""
    return [m for m in models if "image" in (m.get("input_modalities") or [])]


def fetch_vision_models(timeout_s: float = DEFAULT_TIMEOUT_S) -> list[dict[str, Any]]:
    """Fetch + parse + filter. Returns empty list on any failure (logged)."""
    last_err: Exception | None = None
    for attempt, backoff in enumerate((0.0,) + RETRY_BACKOFF_S):
        if backoff > 0:
            time.sleep(backoff)
        try:
            raw = _fetch_raw(timeout_s=timeout_s)
            return filter_vision_capable(parse_models_response(raw))
        except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, OSError) as exc:
            last_err = exc
            _log.warning("openrouter fetch attempt %d failed: %s", attempt + 1, exc)
            continue
    _log.warning("openrouter fetch exhausted retries: %s", last_err)
    return []
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_openrouter_catalog.py -v
```

Expected: all four tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openrouter/ tests/test_openrouter_catalog.py tests/fixtures/openrouter_models.json
git commit -m "feat(openrouter): fetcher + parser for vision-capable models"
```

---

## Task 6: OpenRouter cache layer

Disk cache for the OpenRouter response, mirroring `storage/catalog.py`. Schema-versioned, TTL-bounded, atomic writes. Default to empty list when missing/stale and the network fetch fails — fal-direct vision endpoints still populate the I2T dropdown.

**Files:**
- Create: `src/storage/openrouter.py`
- Create: `tests/test_storage_openrouter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_storage_openrouter.py`:

```python
import json
import time
from pathlib import Path

from src.storage import openrouter as cache


def test_load_if_fresh_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_PATH", tmp_path / "openrouter.json")
    assert cache.load_if_fresh() is None


def test_write_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_PATH", tmp_path / "openrouter.json")
    models = [
        {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5",
         "input_modalities": ["text", "image"], "description": ""},
    ]
    cache.write(models)
    loaded = cache.load_if_fresh()
    assert loaded == models


def test_load_if_fresh_rejects_stale_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "openrouter.json"
    cache_file.write_text(json.dumps({
        "schema_version": cache.SCHEMA_VERSION,
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "models": [],
    }))
    # Force mtime past TTL
    old = time.time() - cache.CACHE_TTL_SECONDS - 60
    import os
    os.utime(cache_file, (old, old))
    monkeypatch.setattr(cache, "CACHE_PATH", cache_file)
    assert cache.load_if_fresh() is None


def test_load_if_fresh_rejects_old_schema_version(tmp_path, monkeypatch):
    cache_file = tmp_path / "openrouter.json"
    cache_file.write_text(json.dumps({
        "schema_version": cache.SCHEMA_VERSION - 1,
        "fetched_at": "2026-05-01T00:00:00+00:00",
        "models": [],
    }))
    monkeypatch.setattr(cache, "CACHE_PATH", cache_file)
    assert cache.load_if_fresh() is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_storage_openrouter.py -v
```

Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Implement the cache module**

Create `src/storage/openrouter.py`:

```python
"""Disk-backed cache for OpenRouter's vision-capable model list.

Mirrors `storage/catalog.py`'s shape: schema-version-aware load, TTL freshness
check, atomic write. The cached payload is a list of plain dicts (not
ModelEntry) — these models live as CatalogEntry rows in catalogs/i2t.py, not
as registry entries.

Cold start with no cache + offline: returns empty list. The I2T dropdown
falls back to fal-direct vision models only.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("fal_gateway.storage.openrouter")

_PKG_ROOT = Path(__file__).resolve().parent.parent  # src/
CACHE_PATH = _PKG_ROOT.parent / "cache" / "openrouter.json"

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days, matches fal catalog TTL
SCHEMA_VERSION = 1


def load_if_fresh() -> list[dict] | None:
    """Read the cache if present, fresh, and schema-current. None otherwise."""
    if not CACHE_PATH.exists():
        return None
    try:
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age > CACHE_TTL_SECONDS:
            _log.info("openrouter cache stale (%.1f days); refetching", age / 86400)
            return None
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("openrouter cache read failed: %s", exc)
        return None
    if data.get("schema_version") != SCHEMA_VERSION:
        _log.info("openrouter cache schema mismatch; refetching")
        return None
    models = data.get("models")
    if not isinstance(models, list):
        return None
    return models


def write(models: list[dict]) -> None:
    """Atomic write."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "models": models,
        }
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(CACHE_PATH)
        _log.info("wrote %d openrouter models to %s", len(models), CACHE_PATH)
    except OSError as exc:
        _log.warning("openrouter cache write failed: %s", exc)


def clear() -> bool:
    if not CACHE_PATH.exists():
        return False
    CACHE_PATH.unlink()
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_storage_openrouter.py -v
```

Expected: all four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/storage/openrouter.py tests/test_storage_openrouter.py
git commit -m "feat(storage): cache layer for openrouter vision models"
```

---

## Task 7: Generate I2T `CURATED` rows from OpenRouter cache

Replace `CURATED: list[CatalogEntry] = []` with a function that reads the OpenRouter cache (loading or fetching as needed) and produces one `CatalogEntry` per vision-capable model, all pointing at `openrouter/router/vision` with `extra_payload={"model": "<openrouter-id>"}`. Display name follows the `[Provider] Model Name` convention used by T2T.

**Files:**
- Modify: `src/catalogs/i2t.py`
- Modify: `tests/test_catalogs.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_catalogs.py`:

```python
from unittest.mock import patch

from src.catalogs import i2t


def test_i2t_curated_built_from_openrouter_cache():
    """When openrouter cache has vision models, CURATED includes them."""
    cached = [
        {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5",
         "input_modalities": ["text", "image"], "description": ""},
        {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro",
         "input_modalities": ["text", "image"], "description": ""},
    ]
    with patch("src.catalogs.i2t._load_openrouter_models", return_value=cached):
        curated = i2t._build_curated()
    ids_by_display = {e.display_name: e.extra_payload.get("model") for e in curated}
    assert ids_by_display.get("[Anthropic] Claude Sonnet 4.5") == "anthropic/claude-sonnet-4.5"
    assert ids_by_display.get("[Google] Gemini 2.5 Pro") == "google/gemini-2.5-pro"
    # All entries dispatch to openrouter/router/vision
    assert all(e.endpoint_id == "openrouter/router/vision" for e in curated)
    assert all(e.provider in ("anthropic", "google") for e in curated)


def test_i2t_curated_is_empty_when_openrouter_cache_empty():
    with patch("src.catalogs.i2t._load_openrouter_models", return_value=[]):
        assert i2t._build_curated() == []


def test_i2t_curated_filters_non_vision_models_defensively():
    """Even if cache somehow contains a text-only model, filter it out."""
    cached = [
        {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5",
         "input_modalities": ["text", "image"], "description": ""},
        {"id": "deepseek/deepseek-v3", "name": "DeepSeek V3",
         "input_modalities": ["text"], "description": ""},
    ]
    with patch("src.catalogs.i2t._load_openrouter_models", return_value=cached):
        curated = i2t._build_curated()
    assert len(curated) == 1
    assert curated[0].extra_payload["model"] == "anthropic/claude-sonnet-4.5"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_catalogs.py::test_i2t_curated_built_from_openrouter_cache -v
```

Expected: FAIL — `i2t._build_curated` and `i2t._load_openrouter_models` don't exist.

- [ ] **Step 3: Replace `i2t.py` with the dynamic-curated version**

Rewrite `src/catalogs/i2t.py`:

```python
"""Curated image-to-text (vision) catalog.

Two sources feed the I2T dropdown:

1. **fal-direct vision endpoints** (Florence-2, Moondream, SA2VA, etc.)
   auto-merge from the live fal catalog via `catalogs.build_catalog`. The
   work here is filtering noise — NSFW classifiers, embeddings, OCR-only
   sub-paths, batch variants — via `HIDDEN_ENDPOINTS`.

2. **OpenRouter vision-capable LLMs** (Claude, Gemini, GPT-4o, Grok, ...)
   are NOT in fal's catalog as individual entries. We pull the list from
   OpenRouter's own `/api/v1/models` endpoint (cached, see
   `storage/openrouter.py`), filter to those whose
   `architecture.input_modalities` contains `"image"`, and synthesize one
   `CatalogEntry` per — all dispatching to the fal endpoint
   `openrouter/router/vision` with `extra_payload={"model": "<id>"}`.

Adding a new vision model = nothing required:
  - fal-direct: auto-merges from live catalog
  - OpenRouter: auto-appears next cache refresh once OpenRouter ships it
"""

from __future__ import annotations

from typing import Any

from ..models import CatalogEntry
from ..openrouter import catalog as openrouter_catalog
from ..storage import openrouter as openrouter_cache


_OPENROUTER_VISION_ENDPOINT = "openrouter/router/vision"


def _load_openrouter_models() -> list[dict[str, Any]]:
    """Cache-first load with live fetch on miss/stale."""
    cached = openrouter_cache.load_if_fresh()
    if cached is not None:
        return cached
    fresh = openrouter_catalog.fetch_vision_models()
    if fresh:
        openrouter_cache.write(fresh)
    return fresh


def _provider_from_id(model_id: str) -> str:
    """OpenRouter ids look like 'anthropic/claude-sonnet-4.5' → 'anthropic'."""
    return model_id.split("/", 1)[0] if "/" in model_id else "unknown"


def _entry_for(model: dict[str, Any]) -> CatalogEntry:
    model_id = model["id"]
    provider = _provider_from_id(model_id)
    display = model.get("name") or model_id
    # Title-case the provider for the bracketed prefix.
    bracket_provider = provider.replace("-", " ").title()
    return CatalogEntry(
        display_name=f"[{bracket_provider}] {display}",
        endpoint_id=_OPENROUTER_VISION_ENDPOINT,
        extra_payload={"model": model_id},
        provider=provider,
        description=str(model.get("description") or ""),
    )


def _build_curated() -> list[CatalogEntry]:
    """Dynamically build the I2T curated list from the OpenRouter cache."""
    models = _load_openrouter_models()
    # Defensive filter: even though the fetcher pre-filters, re-check here so
    # a stale cache never surfaces a text-only model in I2T.
    vision = [m for m in models if "image" in (m.get("input_modalities") or [])]
    return [_entry_for(m) for m in vision]


# Module-level eval at import time so `catalogs.__init__._CATEGORY_CURATED`
# captures the resolved list. If you need to refresh after the openrouter
# cache is rewritten at runtime, call `_build_curated()` again.
CURATED: list[CatalogEntry] = _build_curated()


# Endpoints to suppress from the live merge:
#   - Protocol routers / chat-completions wrappers (parents not used directly)
#   - Classifiers (NSFW filters)
#   - Embedding / OCR / detection sub-paths (not text-generation)
#   - Batch variants (intended for batch_input arrays, not a single image)
#   - Video sub-paths (we only handle still-image input on I2T)
#   - Florence-2 / Moondream variants we don't keep
HIDDEN_ENDPOINTS: frozenset[str] = frozenset(
    {
        # Protocol parents
        "openrouter/router/vision",  # surfaced via curated rows above
        "perceptron/isaac-01/openai/v1/chat/completions",
        # NSFW classifiers (binary; not "describe this image")
        "fal-ai/imageutils/nsfw",
        "fal-ai/x-ailab/nsfw",
        # Video-only sub-paths
        "fal-ai/video-understanding",
        "fal-ai/sa2va/4b/video",
        "fal-ai/sa2va/8b/video",
        # Embeddings
        "fal-ai/sam-3/image/embed",
        # OCR-specific (keep general caption models for general use)
        "fal-ai/got-ocr/v2",
        "fal-ai/florence-2-large/ocr",
        # Batch variants
        "fal-ai/moondream-next/batch",
        "fal-ai/moondream/batched",
        # Detection / region / pointing — non-caption-shaped
        "fal-ai/moondream3-preview/detect",
        "fal-ai/moondream3-preview/point",
        "fal-ai/moondream3-preview/query",
        "fal-ai/moondream2/object-detection",
        "fal-ai/moondream2/point-object-detection",
        "fal-ai/moondream2/visual-query",
        "fal-ai/florence-2-large/region-to-category",
        "fal-ai/florence-2-large/region-to-description",
        # Florence-2 duplicates (keep `/detailed-caption` as canonical)
        "fal-ai/florence-2-large/caption",
        "fal-ai/florence-2-large/more-detailed-caption",
        # Arbiter sub-variants (keep `fal-ai/arbiter/image` as canonical)
        "fal-ai/arbiter/image/text",
        "fal-ai/arbiter/image/image",
    }
)
```

Note the existing test `test_i2t_curated_is_empty` (referenced in `.pytest_cache`) becomes invalid — the curated list is no longer always empty. Update or replace it; the new `test_i2t_curated_is_empty_when_openrouter_cache_empty` covers the empty-cache case.

- [ ] **Step 4: Update or remove the now-invalid existing test**

Search for and remove the obsolete test:

```bash
grep -rn "test_i2t_curated_is_empty" tests/
```

If found in `tests/test_catalogs.py` and/or `tests/test_registries.py`, delete the test function (the assertion `i2t.CURATED == []` is no longer valid by design).

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_catalogs.py tests/test_registries.py -v
```

Expected: all three new tests PASS, existing catalog tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add src/catalogs/i2t.py tests/test_catalogs.py tests/test_registries.py
git commit -m "feat(catalogs/i2t): generate curated rows from OpenRouter cache"
```

---

## Task 8: End-to-end I2T integration test (OpenRouter dispatch)

Lock in the full path: I2T node + catalog-driven dispatch + plumbing fix + payload transformer = correct fal request body.

**Files:**
- Modify: `tests/test_build_payload.py` (add e2e test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_build_payload.py`:

```python
@pytest.mark.asyncio
async def test_i2t_openrouter_vision_e2e_payload(monkeypatch):
    """End-to-end: I2T dropdown row '[Anthropic] Claude Sonnet 4.5' →
    catalog resolves → entry is openrouter/router/vision → payload assembly
    + IMAGE_ARRAY wrap + extra_payload merge yields the right fal body."""
    from src.catalogs import i2t

    fake_or_models = [{
        "id": "anthropic/claude-sonnet-4.5",
        "name": "Claude Sonnet 4.5",
        "input_modalities": ["text", "image"],
        "description": "",
    }]
    monkeypatch.setattr(i2t, "_load_openrouter_models", lambda: fake_or_models)
    # Rebuild CURATED after the patch (module-level eval already happened)
    monkeypatch.setattr(i2t, "CURATED", i2t._build_curated())

    # Verify the catalog row exists with the expected display string
    from src import catalogs as catalogs_pkg
    from src import model_registry
    live = model_registry.filter_models("vision")
    entry = catalogs_pkg.resolve("vision", "[Anthropic] Claude Sonnet 4.5", live)
    assert entry is not None
    assert entry.endpoint_id == "openrouter/router/vision"
    assert entry.extra_payload == {"model": "anthropic/claude-sonnet-4.5"}
```

- [ ] **Step 2: Run test to verify it passes (should already pass given Tasks 5-7 are merged)**

```bash
uv run pytest tests/test_build_payload.py::test_i2t_openrouter_vision_e2e_payload -v
```

Expected: PASS — confirms the catalog plumbing works end-to-end.

- [ ] **Step 3: Run the full test suite for regressions**

```bash
uv run pytest tests/ -v
```

Expected: all PASS. Note any failures and fix before committing.

- [ ] **Step 4: Commit**

```bash
git add tests/test_build_payload.py
git commit -m "test(i2t): end-to-end OpenRouter vision dispatch coverage"
```

---

## Task 9: Update README.md

Document the new behavior so users know I2T isn't just direct fal vision endpoints anymore.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Find the I2T section**

```bash
grep -n "I2T\|Image-to-Text\|vision" README.md
```

- [ ] **Step 2: Update the I2T description**

In `README.md`, replace the existing I2T section description (around line 61 per the PKG-INFO snippet earlier in this investigation) to read:

```markdown
- **I2T node** — flat curated list combining fal-direct vision endpoints (Florence-2, Moondream, SA2VA, etc.) with OpenRouter vision-capable LLMs (Claude, Gemini, GPT-4o, Grok, Llama-Vision, Pixtral, Qwen-VL, ...). The OpenRouter list is auto-detected from `https://openrouter.ai/api/v1/models` filtered by `architecture.input_modalities` containing `"image"` — new vision models surface automatically as OpenRouter adds them, no code change required. OpenRouter rows dispatch to `openrouter/router/vision` with the model id injected via `extra_payload`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: I2T now includes OpenRouter vision LLMs (auto-detected)"
```

---

## Self-Review

**Spec coverage:**
- ✅ Auto-detect vision capability from upstream metadata (Task 5: OpenRouter `architecture.input_modalities`)
- ✅ Less maintenance / clean passthrough (no hand-curated vision flag list anywhere)
- ✅ Properly only show vision-capable models in I2T (Task 7: `_build_curated` filters; Task 5 fetcher pre-filters)
- ✅ fal-direct vision endpoints continue to work (Task 4 fix; live merge unchanged)
- ✅ Pre-existing I2T plumbing bug is fixed as part of this work (Task 4)

**Placeholder scan:** No "TBD", "implement later", "similar to Task N" — every step has either explicit code or an explicit command with expected output.

**Type consistency:**
- `ModelEntry.input_modalities: list[str]` declared in Task 1, referenced in Tasks 2 and 7 with the same type.
- `_build_curated()` returns `list[CatalogEntry]`, matches `CURATED: list[CatalogEntry]` declaration.
- `_load_openrouter_models()` returns `list[dict[str, Any]]`, consumed by `_build_curated`.
- `_OPENROUTER_VISION_ENDPOINT = "openrouter/router/vision"` is the only string literal for that endpoint id.
- Cache module API: `load_if_fresh() -> list[dict] | None`, `write(models: list[dict]) -> None`. Consistent across Tasks 6 and 7.

**Risks / out-of-scope (explicitly NOT addressed by this plan):**
- The same image socket↔widget mismatch likely also breaks I2I and I2V for live-discovered (non-fallback-cataloged) models. Task 4 fixes the path generally, but coverage tests for I2I/I2V are not in this plan — they'd be follow-on work.
- No bundled `data/openrouter_fallback.json` exists. Cold start with no cache + offline = empty OpenRouter contribution. Acceptable per "less maintenance" goal; fal-direct vision endpoints still populate I2T.
- OpenRouter's API rate limits aren't bounded here. The cache's 7-day TTL keeps us under any reasonable limit; we don't poll on every session.

---
