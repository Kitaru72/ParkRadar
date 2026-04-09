from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR


def main() -> None:
    db_path = DATA_DIR / "parkradar.db"
    uploads = DATA_DIR / "uploads"
    if db_path.exists():
        db_path.unlink()
    if uploads.exists():
        shutil.rmtree(uploads)
    print("Demo data reset. Next app start will reseed the project.")


if __name__ == "__main__":
    main()
