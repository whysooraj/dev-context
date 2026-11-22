"""
dev_context module: Exposes functions from bin/dev-context for programmatic and test usage.
"""

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

_bin_path = Path(__file__).resolve().parent / "bin" / "dev-context"
_loader = SourceFileLoader("dev_context_bin", str(_bin_path))
_spec = importlib.util.spec_from_loader("dev_context_bin", _loader)
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

# Expose symbols
for _k, _v in _mod.__dict__.items():
    if not _k.startswith("_"):
        globals()[_k] = _v
