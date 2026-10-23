import json
from io import StringIO

import pytest

from app.config import settings
from app.images import get_image_url, safe_image_url
from pipeline.images import extract_images


@pytest.mark.parametrize(
    "url",
    [
        "http://fimgs.net/mdimg/perfume/375x500.1.jpg",
        "https://fimgs.net.evil.example/mdimg/perfume/375x500.1.jpg",
        "https://user@fimgs.net/mdimg/perfume/375x500.1.jpg",
        "https://fimgs.net/mdimg/perfume/375x500.1.jpg?token=secret",
        "javascript:alert(1)",
        None,
    ],
)
def test_reject_untrusted_image_urls(url):
    assert safe_image_url(url) is None


def test_extract_picture_or_thumbnail_without_using_guesswork():
    data = [
        {"id": 1, "picture": "https://fimgs.net/mdimg/perfume/375x500.999.jpg"},
        {"id": 2, "thumbnail": "https://fimgs.net/mdimg/perfume/m.2.jpg"},
        {"id": 3, "picture": "https://evil.example/a.jpg"},
        {"id": True, "picture": "https://fimgs.net/mdimg/perfume/m.4.jpg"},
    ]
    images = extract_images(StringIO("\n".join(json.dumps(row) for row in data)))
    assert images == {
        "1": "https://fimgs.net/mdimg/perfume/375x500.999.jpg",
        "2": "https://fimgs.net/mdimg/perfume/m.2.jpg",
    }


def test_image_catalog_is_optional_and_reloads_when_built(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert get_image_url(1) is None
    target = tmp_path / "processed" / "images.json"
    target.parent.mkdir()
    target.write_text(json.dumps({"1": "https://fimgs.net/mdimg/perfume/m.1.jpg"}))
    assert get_image_url(1) == "https://fimgs.net/mdimg/perfume/m.1.jpg"
    target.write_text(json.dumps({"1": "https://fimgs.net/mdimg/perfume/375x500.111.jpg"}))
    assert get_image_url(1) == "https://fimgs.net/mdimg/perfume/375x500.111.jpg"
