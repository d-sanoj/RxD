"""Seed the demo users, the 30 synthetic patients and the label chunks. Safe to run again (idempotent).

    python scripts/seed.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.models.container import build_container  # noqa: E402
from app.models.seed_service import seed_all  # noqa: E402


def main() -> None:
    configure_logging()
    container = build_container(get_settings())
    counts = seed_all(container)
    print("Seed complete:", counts)
    print("Sign in at http://localhost:8000 with dr.evans (clinician), rph.aniket (pharmacist) or admin.sanoj (admin).")


if __name__ == "__main__":
    main()
