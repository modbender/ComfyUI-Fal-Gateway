# Changelog

All notable changes to ComfyUI-Fal-Gateway will be documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [0.2.0] — 2026-04-26

### Added
- Four new image nodes:
  - `FalGatewayT2I` — `Fal Text-to-Image`
  - `FalGatewayI2I` — `Fal Image-to-Image`
  - `FalGatewayRef2I` — `Fal Reference-to-Image` (FLF + multi-reference, with the same dynamic `image_count` switch as Ref2V)
  - `FalUpscale` — `Fal Upscale` (dropdown auto-populated from `image-to-image` models flagged as upscalers via tag / endpoint name / description heuristics)
- `src/output_decoder.py` — image bytes → ComfyUI tensor + per-kind URL extraction. Routes video to cv2 decoder (existing) and image to PIL decoder (new).
- Schema resolver now detects `shape == "upscale"` for image-to-image models matching upscale heuristics. New `metadata` and `endpoint_id` kwargs on `parse_openapi(...)`.
- `model_registry` now accepts and stores `text-to-image` and `image-to-image` categories from the live catalog.
- `catalog_client.fetch_active_video_models` (kept name for compat) defaults to fetching all four current categories: T2V / I2V / T2I / I2I. Pass `categories=...` to narrow.
- New example workflows: `examples/workflows/flux_dev_t2i.json`, `examples/workflows/upscale_real_esrgan.json`.
- 18 new unit tests covering the output decoder + 8 new tests covering upscale shape detection.

### Changed
- `_FalGatewayNodeBase` now declares an `OUTPUT_KIND` classvar (default `"video"`). Image subclasses set `"image"`. The base `execute()` dispatches via `output_decoder.decode_artifact(url, kind)` instead of hardcoded video calls.
- Frontend right-click "refresh catalog cache" menu now appears on all seven node types (was three).
- Frontend dynamic `image_count` socket sync now applies to both Ref2V and Ref2I (was Ref2V-only).

### Notes
- Ref2I default `image_count` is 2 (matches Ref2V). Bump to 3 or 4 for multi-reference models.
- Upscale heuristic uses tags, endpoint name regex, and description keywords — see `_looks_like_upscale` in `src/schema_resolver.py`. False positives can be silenced via a future `shape_override` field in `fallback_catalog.json`; not yet wired.
- LLM / VLM (text outputs) deferred to a later v0.x release.

## [0.1.0] — 2026-04-25

### Added
- M1: three node classes (`FalGatewayT2V`, `FalGatewayI2V`, `FalGatewayRef2V`) with hardcoded MVP model list (6 models).
- M1: async fal-client wrappers for upload, subscribe, and video frame decode.
- M2: schema resolver — OpenAPI 3.0 → WidgetSpec list + shape detection (text_only / single_image / flf / multi_ref).
- M3: live catalog fetch via `https://api.fal.ai/v1/models`, disk cache with 7-day TTL, schema-version invalidation.
- Right-click "refresh catalog cache" menu on gateway nodes; backend route at POST /fal_gateway/refresh.
- Dynamic `image_count` switch on Ref2V — declares 4 max image sockets, frontend hides extras.
- Integration test suite (`pytest -m integration`) hitting the live fal.ai catalog.
