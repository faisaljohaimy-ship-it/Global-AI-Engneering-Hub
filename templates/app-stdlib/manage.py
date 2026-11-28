#!/usr/bin/env python3
"""Entry point that also works under `python3 -I` (isolated mode): python3 manage.py serve."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from app.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
