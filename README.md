# ComfyUI-Fal-Gateway

Schema-driven ComfyUI gateway for **fal.ai**. Seven unified nodes — Text/Image/Reference for both **video** and **image** generation, plus a dedicated **Upscale** node — that auto-populate from fal's model catalog. New fal models appear in the dropdown automatically. No per-model code required.

> **Status:** v0.2.0 (alpha). Video + Image + Upscale shipped. LLM / VLM deferred.

## Why

Existing ComfyUI integrations for fal.ai follow the "one Python class per model" pattern. Every new fal model — Seedance 2 FLF, Veo 3.1, Kling V3, etc. — needs a wrapper class, a PR, and a release. As of April 2026, that pipeline lags fal's catalog by weeks-to-months.

This gateway uses **fal's own OpenAPI schemas** to render widgets dynamically. Catalog grows → dropdown grows. Period.

## Nodes (v0.2.0)

| Node | Category filter | Use for | Output |
|---|---|---|---|
| `Fal Text-to-Video` | `text-to-video` | Veo 3.1 T2V, Kling V3 T2V, Seedance T2V, Wan 2.6 T2V | IMAGE (frames), STRING (URL) |
| `Fal Image-to-Video` | `image-to-video`, single-image shape | Seedance 2 I2V, Kling I2V, Veo I2V, MiniMax | IMAGE (frames), STRING (URL) |
| `Fal Reference-to-Video` | `image-to-video`, FLF + multi-ref shapes | Kling 2.5 Turbo Pro FLF, Veo 3.1 FLF, Seedance 2 reference-to-video | IMAGE (frames), STRING (URL) |
| `Fal Text-to-Image` | `text-to-image` | FLUX.1 [dev], Recraft, SDXL, etc. | IMAGE, STRING (URL) |
| `Fal Image-to-Image` | `image-to-image`, single-image shape | Style transfer, img2img variants, Flux fill | IMAGE, STRING (URL) |
| `Fal Reference-to-Image` | `image-to-image`, FLF + multi-ref shapes | IP-Adapter / subject-reference / multi-ref image models | IMAGE, STRING (URL) |
| `Fal Upscale` | `image-to-image` flagged as upscale | Real-ESRGAN, Clarity Upscaler, Crystal Upscaler, etc. (auto-detected from tags / endpoint name / description) | IMAGE, STRING (URL) |

## Install (development)

1. Clone (or symlink) into your ComfyUI custom_nodes folder.

   On Windows + WSL development (no admin needed):
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

All seven nodes appear under category `Fal-Gateway` in the "Add Node" menu.

## Use

### Video example (existing)
- Drop a `Fal Image-to-Video` node onto the canvas.
- Pick a model from the dropdown (type-ahead search works for the 100+ I2V models).
- Wire a `LoadImage` into the `image` input, type a prompt, click Queue.
- Output: an `IMAGE` frames batch (works with `VHS_VideoCombine`, `SaveVideo`) plus a `STRING` source URL.

### Image example (new in v0.2.0)
- Drop a `Fal Text-to-Image` node onto the canvas.
- Pick a model (FLUX.1 dev, Recraft, etc.).
- Type a prompt, click Queue.
- Output: a 1-frame `IMAGE` tensor (works with `SaveImage`) plus a `STRING` source URL.

### Upscale example (new in v0.2.0)
- Drop a `Fal Upscale` node, wire a `LoadImage` → `image` socket.
- Pick e.g. `fal-ai/esrgan` from the dropdown.
- Click Queue. Upscaled image saves via `SaveImage` downstream.

See [`examples/workflows/`](examples/workflows/) for drop-in templates:
- `seedance_pro_i2v.json` — image-to-video
- `flux_dev_t2i.json` — text-to-image
- `upscale_real_esrgan.json` — image upscale

## Right-click "Refresh catalog cache"

If the dropdown contents look stale, right-click any Fal-Gateway node and pick "Fal-Gateway: refresh catalog cache". The cache deletes and a fresh fetch starts in the background. **Restart ComfyUI** for the new dropdown options to take effect on existing nodes.

Diagnostic: `GET http://127.0.0.1:8188/fal_gateway/health` returns `{fal_key_present, model_count}`.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
