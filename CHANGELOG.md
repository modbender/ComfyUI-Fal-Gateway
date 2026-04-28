# Changelog

All notable changes to ComfyUI-Fal-Gateway will be documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [0.2.0] — 2026-04-26

### Added
- **Image generation nodes** — `FalGatewayT2I`, `FalGatewayI2I`, `FalGatewayRef2I` (FLF + multi-ref), `FalUpscale` (auto-detected upscale models). Categories supported: text-to-image, image-to-image, plus the existing video.
- **Audio output on video nodes** — T2V/I2V/Ref2V now emit `audio` (AUDIO type) alongside `frames` and `video_url`. Extracted from the downloaded mp4 via ffmpeg subprocess; silently `None` if the model produced silent video or ffmpeg is missing. Wires straight into VHS_VideoCombine's `audio` input.
- **`info` STRING output** on every node — JSON-encoded full fal result. Surfaces seed, timings, has_nsfw_concepts, etc. without cluttering the node with dedicated sockets.
- **M4: per-model dynamic widget rendering.** Frontend hooks the model dropdown's callback; on change it fetches `/fal_gateway/schema/<id_b64>` and rebuilds the node's per-model widgets (duration, aspect_ratio, resolution, seed, cfg_scale, etc.) in place. Cached client-side. Saved workflow values restored after rebuild.
- **Display-string model dropdown** — dropdown options are now `[provider] DisplayName — endpoint_id`, sorted by provider then name. Type-ahead clusters families together (`kling`, `seedance`, `veo`).
- `src/output_decoder.py` — image bytes → ComfyUI tensor + per-kind URL extraction.
- Schema resolver detects `shape == "upscale"` for image-to-image models via tag / endpoint-name / description heuristics. New `metadata` and `endpoint_id` kwargs on `parse_openapi(...)`.
- New example workflows: `flux_dev_t2i.json`, `upscale_real_esrgan.json`.
- **76 new unit tests** total: output_decoder (18), audio_decoder (6), info_output (6), schema_resolver upscale (8), build_payload M4 contract (13), server_routes b64 (12), display_strings (13).

### Changed
- `_FalGatewayNodeBase.OUTPUT_KIND` classvar (default `"video"`). Image subclasses set `"image"`. The base `execute()` dispatches via `output_decoder.decode_artifact(url, kind)` instead of hardcoded video calls.
- Video nodes' `RETURN_TYPES` now `("IMAGE", "STRING", "AUDIO", "STRING")` (was `("IMAGE", "STRING")`). Existing workflows still work — output indices 0 and 1 are unchanged.
- Image nodes' `RETURN_TYPES` is `("IMAGE", "STRING", "STRING")` with names `("image", "image_url", "info")`.
- I2V / I2I dropdowns now include FLF-shape models too (they work as plain single-image when only the start image is wired).
- Frontend right-click "refresh catalog cache" menu now appears on all seven node types.
- Frontend dynamic `image_count` socket sync now applies to both Ref2V and Ref2I.

### Fixed
- **Schema endpoint base64 decoding** — JS strips padding from `btoa()` output (RFC 4648 §3.2); Python's `urlsafe_b64decode` is strict. Models whose IDs encoded to non-multiple-of-4 lengths (e.g. `bytedance/seedance-2.0/image-to-video`) returned 400. Backend now re-pads before decoding.
- **Stale dynamic widgets on schema fetch failure** — previous behavior left the prior model's widgets visible if the new model's schema couldn't load. Now widgets are cleared first; failures leave a stripped-down node as a visible signal.
- **Node resize reverts** — `syncImageSockets` was calling `node.setSize(node.computeSize())`, clobbering user-resized dimensions. Now grows to fit but never shrinks past the user's manual size.

### Notes
- `parse_display_string` is strict: raises `ValueError` on raw endpoint IDs or malformed input. The dropdown always writes display strings; saved-workflow back-compat is intentionally NOT supported (early users; clean slate is the priority).
- Upscale heuristic uses tags, endpoint name regex, and description keywords — see `_looks_like_upscale` in `src/schema_resolver.py`.
- LLM / VLM (text outputs) deferred to a later v0.x release.
- Per-model widget save/restore is best-effort: if fal renames a parameter or shifts the schema between save and load, dynamic values may be misaligned.

## [0.1.0] — 2026-04-25

### Added
- M1: three node classes (`FalGatewayT2V`, `FalGatewayI2V`, `FalGatewayRef2V`) with hardcoded MVP model list (6 models).
- M1: async fal-client wrappers for upload, subscribe, and video frame decode.
- M2: schema resolver — OpenAPI 3.0 → WidgetSpec list + shape detection (text_only / single_image / flf / multi_ref).
- M3: live catalog fetch via `https://api.fal.ai/v1/models`, disk cache with 7-day TTL, schema-version invalidation.
- Right-click "refresh catalog cache" menu on gateway nodes; backend route at POST /fal_gateway/refresh.
- Dynamic `image_count` switch on Ref2V — declares 4 max image sockets, frontend hides extras.
- Integration test suite (`pytest -m integration`) hitting the live fal.ai catalog.
