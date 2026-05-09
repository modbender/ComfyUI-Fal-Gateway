# ComfyUI-Fal-Gateway

Schema-driven ComfyUI gateway for **fal.ai**. Nine unified nodes covering video, image, upscale, text-to-text, and image-to-text — all auto-populating from fal's model catalog. New fal models appear in the dropdown automatically with their parameters surfaced as widgets parsed from each model's OpenAPI schema. **No per-model code required.**

> **Status:** active development. Latest features: smart cost-per-run badge in node title bars, decoupled pricing cache with skip-list, curated flat catalog for LLM/VLM models (Anthropic, Google, OpenAI, Meta, etc.), Pydantic at boundaries.

## Why

Existing ComfyUI integrations for fal.ai follow the "one Python class per model" pattern. Every new fal model — Seedance, Kling, Veo, GPT-5, Claude Sonnet, etc. — needs a wrapper class, a PR, and a release. As of 2026, the fal catalog grows faster than that pipeline.

This gateway uses **fal's own OpenAPI schemas** to render widgets dynamically. Catalog grows → dropdown grows. Period.

## Nodes

| Node | Use for | Output |
|---|---|---|
| `Fal Text-to-Video` | Veo 3.1 T2V, Kling V3 T2V, Seedance T2V, Wan 2.6 T2V | IMAGE (frames), STRING (URL), AUDIO, STRING (info) |
| `Fal Image-to-Video` | Seedance 2 I2V, Kling I2V, Veo I2V, MiniMax | IMAGE, STRING, AUDIO, STRING |
| `Fal Reference-to-Video` | Kling 2.5 Turbo Pro FLF, Veo 3.1 FLF, Seedance reference-to-video | IMAGE, STRING, AUDIO, STRING |
| `Fal Text-to-Image` | FLUX.1 [dev], Recraft, SDXL, etc. | IMAGE, STRING (URL), STRING (info) |
| `Fal Image-to-Image` | Style transfer, img2img variants, Flux fill | IMAGE, STRING, STRING |
| `Fal Reference-to-Image` | IP-Adapter / subject-reference / multi-ref image models | IMAGE, STRING, STRING |
| `Fal Upscale` | Real-ESRGAN, Clarity Upscaler, Crystal Upscaler (auto-detected) | IMAGE, STRING, STRING |
| `Fal Text-to-Text` | Claude Sonnet 4.5, GPT-5, Gemini 2.5 Pro, Llama 3.3, DeepSeek R1, Grok, Qwen, Mistral — 30+ via OpenRouter, plus direct fal LLMs (Bytedance Seed, Nemotron). Optional `schema` widget switches the response into structured JSON (see below). | STRING (response), STRING (info) |
| `Fal Image-to-Text` | Flat curated list combining fal-direct vision endpoints (Florence-2, Moondream, Sa2VA, etc.) with OpenRouter vision-capable LLMs (Claude, Gemini, GPT-4o, Grok, Llama-Vision, Pixtral, Qwen-VL, ...). OpenRouter list is auto-detected from `https://openrouter.ai/api/v1/models` filtered by `architecture.input_modalities` containing `"image"` — new vision models surface automatically, no code change required. Vision-only: NSFW filters / OCR / detection variants auto-filtered. Optional `schema` widget switches the response into structured JSON (see below). | STRING (response), STRING (info) |
| `JSON Extract (Single)` | Companion to T2T/I2T schema mode. `(json_string, key, default) → value`. Drop one per field you want to extract. Generic — works with any upstream JSON STRING. | STRING (value) |
| `JSON Extract (Multiple)` | Same idea, fan-out form. One multiline `keys` textarea (comma-separated, e.g. `title, tagline, cta`) → one output socket per parsed key, **named after that key**, count auto-syncs as you edit. Cap = 10. | N × STRING (one per key) |

### What's smart about the dropdowns

- **Video / image / upscale nodes** — populated live from fal's catalog. Restart-free refresh via right-click → "Fal-Gateway: refresh catalog cache". Display strings format as `[provider] DisplayName`, type-ahead clusters families together (`kling`, `seedance`, `veo`).
- **T2T node** — flat curated list. Pick `[Anthropic] Claude Sonnet 4.5` once, no second model picker. Behind the scenes it routes through `openrouter/router/openai/v1/chat/completions` with the model parameter injected. Direct fal LLMs (Bytedance Seed, Nemotron) auto-merge in. NSFW classifiers, OCR sub-paths, embedding endpoints, batch variants etc. are filtered out.
- **I2T node** — flat curated list combining fal-direct vision endpoints with OpenRouter vision-capable LLMs (auto-detected, no code change needed). Dispatch via `openrouter/router/vision` with model id injected. Vision-only variants are filtered out.

### Structured JSON output (T2T / I2T)

Both `Fal Text-to-Text` and `Fal Image-to-Text` have a `schema` widget. Empty by default → free-form text response (current behavior, no change). Fill it with a comma-separated field list → the response becomes a JSON object keyed by those fields, enforced via OpenRouter's `response_format: json_schema` (strict mode).

Example: one Claude call → five named outputs.

```
schema:  flux_ref_prompt, motion_prompt, title, description, tags
response: {"flux_ref_prompt": "...", "motion_prompt": "...", "title": "...", "description": "...", "tags": "..."}
```

Fan it out two ways:

- **`JSON Extract (Multiple)`** — single multiline `keys` textarea, comma-separated. Type `title, tagline, cta` and three output sockets appear named exactly that. Count auto-syncs as you edit. Cap is 10 keys.
- **`JSON Extract (Single)`** — older one-key-at-a-time form. Drop one per field. Useful when keys come from different upstream JSON sources, or when you want explicit per-field defaults.

JSON mode dispatches through OpenRouter (`openrouter/router/openai/v1/chat/completions` for T2T; `openrouter/router/vision` for I2T) and works with most models that support strict structured outputs — Claude Sonnet 4.5+, Gemini 2.5, GPT-4o+, Grok, and many open-source models. Older or smaller variants (Claude 3 Haiku, Llama 3.1 8B, Mistral Small) may not strictly honor the schema; the system-prompt instruction is sent as a fallback hint, but you should set a `default` on the JSON Extract node to circuit-break when a field is missing. fal-direct vision endpoints (Florence-2, Moondream, etc.) silently ignore the schema since they don't honor `response_format`.

### Cost-per-run badge

Every Fal-Gateway node paints an estimated cost in its title bar that updates as you change widget values. Tier-colored: green (cheap) / yellow / orange / red (expensive). Token-priced LLMs show the per-token rate honestly without faking a total.

Pricing comes from fal's `/v1/models/pricing` endpoint, cached separately from the catalog (30-day TTL, persisted skip-list for endpoints fal doesn't price). First node placement after a stale cache triggers a background refresh; cost labels populate within ~30s without blocking ComfyUI startup.

## Install

### Via ComfyUI-Manager *(soon — Manager registry PR pending)*

### Manual install

1. Clone (or symlink) into your ComfyUI `custom_nodes` folder:

   On Windows + WSL development:
   ```bash
   /mnt/c/Windows/System32/cmd.exe /c "mklink /D \
     D:\path\to\ComfyUI\custom_nodes\ComfyUI-Fal-Gateway \
     \\wsl.localhost\Ubuntu\home\you\path\to\ComfyUI-Fal-Gateway"
   ```

2. Install Python dependencies into your ComfyUI venv:
   ```bash
   D:\path\to\ComfyUI\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Set `FAL_KEY`. Either:
   - Environment variable: `FAL_KEY=<your_key>`
   - Or copy `config.ini.example` → `config.ini` and replace the placeholder.

4. Restart ComfyUI.

All nine nodes appear under category `Fal-Gateway` in the "Add Node" menu.

## Use

### Video example
- Drop `Fal Image-to-Video` onto the canvas.
- Pick a model from the dropdown (type-ahead: try `kling` or `seedance`).
- Wire a `LoadImage` into the `image` input, type a prompt, click Queue.
- Output: `IMAGE` frames batch (works with `VHS_VideoCombine`, `SaveVideo`), source URL, audio (mp4-extracted), and a JSON `info` string.

### Text-to-Image example
- Drop `Fal Text-to-Image`, pick `[fal-ai] FLUX.1 [dev]`, type a prompt, Queue.
- Output: 1-frame `IMAGE` tensor (works with `SaveImage`) + source URL + info.

### Upscale example
- Drop `Fal Upscale`, wire `LoadImage` → `image`, pick `[fal-ai] esrgan`, Queue.
- Output: upscaled image saves via `SaveImage` downstream.

### LLM example
- Drop `Fal Text-to-Text`, pick `[Anthropic] Claude Sonnet 4.5` (or any of the 34 entries).
- Type a `prompt`, optionally a `system_prompt`, click Queue.
- Output: STRING response + info JSON.

### Vision (image captioning) example
- Drop `Fal Image-to-Text`, wire a `LoadImage` → `image`, pick `[fal-ai] Moondream2` or any of the 100+ OpenRouter vision models (`[Anthropic] Claude Sonnet 4.5`, `[OpenAI] GPT-4o`, `[Google] Gemini 2.5 Pro`, etc.).
- Type your question/instruction in `prompt` ("describe this image"); optionally set a `system_prompt` ("you are an expert wildlife photographer evaluating composition") to steer the model. Queue.
- Output: STRING caption + info JSON.

> Note: `system_prompt` is honored natively by OpenRouter vision models. Fal-direct endpoints (Florence-2, Moondream, SA2VA, etc.) ignore the field — leave it empty for those.

See [`examples/workflows/`](examples/workflows/) for drop-in templates:
- `seedance_pro_i2v.json` — image-to-video
- `flux_dev_t2i.json` — text-to-image
- `upscale_real_esrgan.json` — image upscale

## Right-click menu

Every Fal-Gateway node has a right-click option **"Fal-Gateway: refresh catalog cache"**. Use it when:
- A new fal model just launched and isn't in your dropdown yet
- Cost labels show "Pricing unavailable" and you want to retry the pricing fetch

The cache is wiped + a background fetch starts. Cost labels live-update via websocket once it completes; the model dropdown options take effect on next ComfyUI restart (or on freshly-placed nodes).

## Diagnostic

```bash
curl http://127.0.0.1:8188/fal_gateway/health
# → {"fal_key_present": true, "model_count": 925}
```

## Companion node

[**ComfyUI-ApproveReject**](https://github.com/modbender/ComfyUI-ApproveReject) — gate any IMAGE/LATENT/MASK/VIDEO_FRAMES output behind a "approve / reject + re-queue with new seed" modal. Pairs naturally with Fal-Gateway for iterating on reference frames without manually re-queueing the whole graph.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
