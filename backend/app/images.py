"""Display-only bottle photos from the dataset, never recommendation features."""

import json
import re
from functools import lru_cache
from urllib.parse import urlsplit

from app.config import settings


def safe_image_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if (
        url.scheme != "https"
        or url.netloc != "fimgs.net"
        or url.query
        or url.fragment
        or not re.fullmatch(r"/mdimg/perfume/(?:375x500|m)\.\d+\.jpg", url.path)
    ):
        return None
    return value


@lru_cache(maxsize=1)
def _load_images(path, modified):
    with open(path) as source:
        values = json.load(source)
    return {str(pid): url for pid, value in values.items() if (url := safe_image_url(value))}


def image_urls():
    path = settings.data_dir / "processed" / "images.json"
    try:
        modified = path.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    return _load_images(str(path), modified)


def get_image_url(perfume_id):
    return image_urls().get(str(perfume_id))
