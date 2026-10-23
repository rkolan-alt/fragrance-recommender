"""Extract display-only image URLs from perfumes.jsonl. No image downloads."""

import json

from app.config import settings
from app.images import safe_image_url


def extract_images(source):
    images = {}
    for line in source:
        if not line.strip():
            continue
        row = json.loads(line)
        pid = row.get("id")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            continue
        image = safe_image_url(row.get("picture")) or safe_image_url(row.get("thumbnail"))
        if image:
            images[str(pid)] = image
    return images


def main():
    source = settings.data_dir / "raw" / "perfumes.jsonl"
    if not source.exists():
        print("Add perfumes.jsonl to data/raw before running make images.")
        return 1
    with source.open() as data:
        images = extract_images(data)
    destination = settings.data_dir / "processed" / "images.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(images, ensure_ascii=False) + "\n")
    temporary.replace(destination)
    print(f"Extracted {len(images):,} bottle photo URLs → {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
