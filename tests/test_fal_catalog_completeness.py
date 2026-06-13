"""C4: fetch_active_video_models must report whether every page of every
category was fetched cleanly, so a partial fetch can't overwrite a good cache."""

from __future__ import annotations

from unittest.mock import patch

from src.fal import catalog as fal_catalog


def _page(models, has_more=False, cursor=None):
    return {"models": models, "has_more": has_more, "next_cursor": cursor}


def test_complete_when_all_pages_fetched_cleanly():
    page = _page([{"endpoint_id": "fal-ai/x", "metadata": {"status": "active"}}])
    with patch.object(fal_catalog, "_fetch_page_with_retries", return_value=page):
        per_cat, complete = fal_catalog.fetch_active_video_models(
            categories=("text-to-image",), with_schemas=False
        )
    assert complete is True
    assert per_cat["text-to-image"][0]["endpoint_id"] == "fal-ai/x"


def test_incomplete_when_a_page_gives_up_after_retries():
    """A None page (exhausted retries) means partial results → incomplete."""
    with patch.object(fal_catalog, "_fetch_page_with_retries", return_value=None):
        per_cat, complete = fal_catalog.fetch_active_video_models(
            categories=("text-to-image",), with_schemas=False
        )
    assert complete is False


def test_incomplete_when_one_of_several_categories_partial():
    calls = {"n": 0}

    def fake_fetch(category, cursor, limit, timeout_s, with_schemas):
        calls["n"] += 1
        if category == "text-to-image":
            return _page([{"endpoint_id": "fal-ai/x", "metadata": {"status": "active"}}])
        return None  # image-to-image fails

    with patch.object(fal_catalog, "_fetch_page_with_retries", side_effect=fake_fetch):
        per_cat, complete = fal_catalog.fetch_active_video_models(
            categories=("text-to-image", "image-to-image"), with_schemas=False
        )
    assert complete is False
    assert per_cat["text-to-image"][0]["endpoint_id"] == "fal-ai/x"


def test_incomplete_when_category_fetch_raises():
    with patch.object(
        fal_catalog, "_fetch_page_with_retries", side_effect=RuntimeError("boom")
    ):
        per_cat, complete = fal_catalog.fetch_active_video_models(
            categories=("text-to-image",), with_schemas=False
        )
    assert complete is False
