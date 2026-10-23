"""Package only the processed public catalog; never raw data, credentials or accounts."""

import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

from app.config import settings

FILES = (
    "perfumes.parquet",
    "features.npz",
    "vocab.json",
    "scores.parquet",
    "clones.parquet",
    "images.json",
)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bundle(source: Path, output: Path):
    from app.engine.catalog import load_catalog

    catalog = load_catalog(source)
    missing = [
        name for name in FILES if not (source / name).is_file() or (source / name).is_symlink()
    ]
    if missing:
        raise ValueError(f"Missing regular artifact files: {missing}")
    manifest = {
        "version": 1,
        "catalog_rows": len(catalog.perfumes),
        "files": {
            name: {"sha256": digest(source / name), "size": (source / name).stat().st_size}
            for name in FILES
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    try:
        with tarfile.open(temporary, "w:gz") as archive:

            def public_metadata(member):
                member.uid = member.gid = 0
                member.uname = member.gname = ""
                return member

            for name in FILES:
                archive.add(source / name, arcname=name, recursive=False, filter=public_metadata)
            encoded = json.dumps(manifest, sort_keys=True, indent=2).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(encoded)
            archive.addfile(info, io.BytesIO(encoded))
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def verify(archive_path: Path):
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if (
            len(names) != len(FILES) + 1
            or set(names) != {*FILES, "manifest.json"}
            or any(not m.isfile() for m in members)
        ):
            raise ValueError("Archive contains unexpected files, duplicates, directories or links")
        manifest_file = archive.extractfile("manifest.json")
        if archive.getmember("manifest.json").size > 100_000:
            raise ValueError("Manifest is too large")
        manifest = json.load(manifest_file)
        if manifest.get("version") != 1 or set(manifest.get("files", {})) != set(FILES):
            raise ValueError("Invalid artifact manifest")
        for name in FILES:
            info = manifest["files"][name]
            stream = archive.extractfile(name)
            if (
                archive.getmember(name).size != info["size"]
                or hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]
            ):
                raise ValueError(f"Artifact checksum or size mismatch: {name}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=settings.data_dir / "processed")
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.data_dir / "processed" / "deployment" / "fragrance-artifacts.tar.gz",
    )
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = verify(args.verify) if args.verify else bundle(args.source, args.output)
    print(
        json.dumps(
            {
                "status": "verified" if args.verify else "packaged",
                "catalog_rows": result["catalog_rows"],
                "files": list(result["files"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
