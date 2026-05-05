# Changelog

All notable changes to ComfyUI-Fal-Gateway will be documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [0.3.0](https://github.com/modbender/ComfyUI-Fal-Gateway/compare/v0.2.0...v0.3.0) (2026-05-05)


### ⚠ BREAKING CHANGES

* `FalUpscale` registered key is now `FalGatewayUpscale`. Re-add the node in any workflows that reference the old name.

### Features

* add LLM and VLM nodes (T2T, I2T); rename FalUpscale to FalGatewayUpscale ([f7bb872](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/f7bb8723fa2c3fa28b2eb6b4fda37f6c6503f3c1))
* clean T2T list and surface OpenRouter Gemini/Claude/GPT models ([ad5c29b](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/ad5c29b34b52ccbea598e66c7d50d37046a2f2cc))
* decouple pricing cache + colored cost-tier badges + bg refresh ([f36ba82](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/f36ba82ceace7b0602fee84e6ba0c181ed557f0b))
* flatten I2T (vision) catalog + rename api_models→models + drop dead shim ([8477d19](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/8477d19307698b83cc44229ccc5e7712d69ad6dc))
* flatten T2T into a single curated model catalog ([4ad790e](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/4ad790eeab34490a7125f03f7c9b5dc371c743e4))
* smart cost estimator widget on every Fal-Gateway node ([71b8fdb](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/71b8fdb1fbb11b0cb9032d28b38c93a4559b267d))


### Bug Fixes

* bisect-on-404 + quieter retry logging in pricing fetch ([4755e08](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/4755e083ecd7bc8e85cfdfb5fafec23204d3fef3))
* bump SCHEMA_VERSION to 3 to invalidate caches missing llm/vision ([37d1c4f](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/37d1c4f30b0a03b0be41a442820282d413a4caa7))
* **ci:** declare src* package in pyproject so pip install -e finds it ([717a336](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/717a336ffb2c4c7bd8f5a0c352f9a90ae98ad2df))
* exclude embeddings endpoints from T2T dropdown ([d5a505b](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/d5a505b2973e47db27f5b96c2207fab530887955))
* **init:** repair stale .src.server_routes import after K-wave rename ([0792e2f](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/0792e2f7ecd0ecbf50288d34e65f5b29a97e4775))
* render cost estimate in node title bar instead of as a widget ([39f9295](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/39f92957e090d47d27338e98107860074660400c))
* shorten dropdown labels by dropping always-on endpoint_id suffix ([f4b430f](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/f4b430f80226ba9d250e295233a8d903c9a39508))
* stable LLM/T2T workflow — fresh fal client, OpenRouter Responses, friendly model names, multiline system_prompt ([f81e4a3](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/f81e4a3af3d54a772566cf5d81656a41b4322575))


### Refactoring

* adopt pydantic at boundaries (fal API, cache I/O, HTTP responses) ([ff5d011](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/ff5d01175240c1805a3148e71306110abf93b681))
* extract catalog cache I/O into src/storage/, move data to src/data/ ([4482343](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/4482343f16936725a5574ad028c4d2483b7b81e4))
* regroup fal_*.py + output_decoder.py under src/fal/ ([ca3122d](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/ca3122dd1da41ade12f98e9868df47ce69e85a6f))
* rename src/registries/ → src/catalogs/ ([08e69e5](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/08e69e5bb0f31b067b0a2be2b9673e65a912654c))
* shorten module names where context already disambiguates ([fc3a272](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/fc3a27253a6830bcf89817e33333fbb7e969c2bb))
* split catalog_client.py into fal/catalog + fal/pricing + _http ([e3bb1ac](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/e3bb1aca24d94e98985d24a938ef1aa998b95fc0))


### Tests

* aiohttp TestClient coverage for all 4 HTTP routes ([db0c8e5](https://github.com/modbender/ComfyUI-Fal-Gateway/commit/db0c8e5bd8b632b2b7039ad5b8346e13e327a7ba))

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
