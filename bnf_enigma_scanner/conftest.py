"""Make `bnf_scanner` importable whether pytest is run from this directory or
from the repository root (the EA sources live alongside it, so the root is a
perfectly normal place to invoke pytest from).

conftest.py is loaded per-directory regardless of pytest's rootdir, so this one
fix covers both invocations without an installed package or a PYTHONPATH shim.
"""

import sys
from pathlib import Path

_PACKAGE_ROOT = str(Path(__file__).resolve().parent)
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)
