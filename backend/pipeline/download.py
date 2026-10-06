"""Download the Fragrantica perfumes dataset from Kaggle into data/raw/.

Requires a Kaggle API token at ~/.kaggle/kaggle.json
(Kaggle → Settings → API → Create New Token).
"""

import sys

from app.config import settings

DATASET = "ledecanteur/fragrantica-perfumes"
FILES = ["perfumes.csv", "SCHEMA.md"]


def main() -> int:
    from kaggle.api.kaggle_api_extended import KaggleApi  # authenticates on import

    api = KaggleApi()
    api.authenticate()
    raw_dir = settings.data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        print(f"Downloading {name} …")
        api.dataset_download_file(DATASET, name, path=raw_dir, force=False, quiet=False)
        zipped = raw_dir / f"{name}.zip"
        if zipped.exists():
            import zipfile

            with zipfile.ZipFile(zipped) as zf:
                zf.extractall(raw_dir)
            zipped.unlink()
    print(f"Done → {raw_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
