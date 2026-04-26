"""Shared backend for all three Fal-Gateway nodes.

M1 scope: dropdown of hardcoded models, fixed `prompt` widget, statically-declared
image sockets (count varies per subclass). Non-image params take WidgetSpec
defaults — frontend dynamic widget rendering lands in M4.

Each subclass overrides:
- `CATEGORY_FILTER` — fal model `category` value to filter the dropdown.
- `SHAPE_FILTER`     — tuple of fal shapes to include in the dropdown.
- `image_socket_names()` — names of statically-declared IMAGE sockets in `required`.
- `optional_image_socket_names()` — names of additional IMAGE sockets in `optional`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, ClassVar

from .. import model_registry
from ..fal_config import default_config
from ..fal_runner import run_async
from ..fal_uploads import upload_tensor_image
from ..output_decoder import decode_artifact, extract_artifact_url
from ..widget_spec import ModelEntry, WidgetSpec


_log = logging.getLogger("fal_gateway.nodes")


def _serialize_info(result: Any) -> str:
    """Serialize a fal result dict to a JSON string for the `info` output.

    Non-serializable values fall through `default=str` (yielding their repr)
    so unexpected payload shapes don't crash the node — diagnostic output is
    best-effort, not authoritative.
    """
    try:
        return json.dumps(result, default=str, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return json.dumps({"_serialize_error": str(exc)})


def _coerce(value: Any, kind: str) -> Any:
    if value is None:
        return None
    try:
        if kind == "INT":
            return int(value)
        if kind == "FLOAT":
            return float(value)
        if kind == "BOOLEAN":
            if isinstance(value, str):
                return value.lower() in ("1", "true", "yes", "on")
            return bool(value)
    except (TypeError, ValueError):
        return value
    return value


class _FalGatewayNodeBase:
    CATEGORY_FILTER: ClassVar[str] = ""
    SHAPE_FILTER: ClassVar[tuple[str, ...]] = ()
    NODE_DISPLAY_LABEL: ClassVar[str] = "Fal Gateway"
    # Output kind drives the artifact decoder (video → cv2, image → PIL).
    # Defaults to "video" so the existing T2V/I2V/Ref2V subclasses don't need to
    # set anything; image subclasses override.
    OUTPUT_KIND: ClassVar[str] = "video"

    # Default RETURN shape covers the video case (which is the base default
    # OUTPUT_KIND). Image subclasses override both RETURN_TYPES and RETURN_NAMES
    # to drop the AUDIO output.
    #   `info` is a JSON-encoded dump of fal's full result dict — useful for
    #   pulling out seed, timings, has_nsfw_concepts, etc. via downstream
    #   text/JSON nodes. Power-user output; safe to leave unwired.
    RETURN_TYPES = ("IMAGE", "STRING", "AUDIO", "STRING")
    RETURN_NAMES = ("frames", "video_url", "audio", "info")
    FUNCTION = "execute"
    CATEGORY = "Fal-Gateway"
    OUTPUT_NODE = False

    @classmethod
    def image_socket_names(cls) -> tuple[str, ...]:
        return ()

    @classmethod
    def optional_image_socket_names(cls) -> tuple[str, ...]:
        return ()

    @classmethod
    def extra_required_widgets(cls) -> dict[str, Any]:
        """Subclass hook to inject extra non-image widgets (e.g. image_count on Ref2V)."""
        return {}

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        ids = model_registry.list_ids(
            cls.CATEGORY_FILTER, cls.SHAPE_FILTER or None
        ) or ["<no models available>"]

        required: dict[str, Any] = {
            "model_id": (ids, {}),
            "prompt": ("STRING", {"default": "", "multiline": True}),
        }
        required.update(cls.extra_required_widgets())
        for name in cls.image_socket_names():
            required[name] = ("IMAGE",)

        optional: dict[str, Any] = {}
        for name in cls.optional_image_socket_names():
            optional[name] = ("IMAGE",)

        return {
            "required": required,
            "optional": optional,
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    async def execute(
        self,
        model_id: str,
        prompt: str,
        unique_id: str | int | None = None,
        **kwargs: Any,
    ) -> tuple[Any, str]:
        cfg = default_config()
        if not cfg.is_configured:
            raise RuntimeError(
                "FAL_KEY not set. Set the FAL_KEY environment variable or copy "
                "config.ini.example to config.ini in the package directory."
            )

        entry = model_registry.get(model_id)
        if entry is None:
            raise RuntimeError(f"unknown model_id {model_id!r}")

        payload = await self._build_payload(entry, prompt, kwargs)
        _log.info("submitting fal job: model=%s payload_keys=%s", model_id, list(payload.keys()))
        result = await run_async(model_id, payload)
        kind = type(self).OUTPUT_KIND
        url = extract_artifact_url(result, kind)

        info = _serialize_info(result)

        if kind == "video":
            # Video nodes return (frames, url, audio, info) — audio may be None
            # for silent clips or when ffmpeg isn't available. VHS_VideoCombine's
            # audio input is optional, so None is fine downstream.
            from ..fal_downloads import fetch_video_with_audio

            frames, audio = await fetch_video_with_audio(url)
            return (frames, url, audio, info)

        # Image nodes return (image, url, info).
        artifact = await decode_artifact(url, kind)
        return (artifact, url, info)

    async def _build_payload(
        self,
        entry: ModelEntry,
        prompt: str,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        widgets_by_name = {w.name: w for w in entry.widgets}

        # 1. Prompt is always present at the static level; map to its payload key
        prompt_widget = widgets_by_name.get("prompt")
        if prompt_widget is not None and prompt:
            payload[prompt_widget.fal_key] = prompt

        # 2. Image sockets: upload tensors → URLs at each widget's payload_key
        for w in entry.widgets:
            if w.kind not in ("IMAGE_INPUT", "IMAGE_ARRAY"):
                continue
            tensor = kwargs.get(w.name)
            if tensor is None:
                if w.required:
                    raise RuntimeError(f"required image input {w.name!r} not connected")
                continue
            url = await upload_tensor_image(tensor)
            payload[w.fal_key] = url

        # 3. Non-image widgets — M1 uses WidgetSpec defaults; M4 will read from kwargs once
        #    the frontend renders these widgets dynamically.
        for w in entry.widgets:
            if w.kind in ("IMAGE_INPUT", "IMAGE_ARRAY") or w.name == "prompt":
                continue
            value = kwargs.get(w.name, w.default)
            if value is None or value == "":
                continue
            payload[w.fal_key] = _coerce(value, w.kind)

        return payload
