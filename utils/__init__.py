"""
Expose utilities from top-level utils.py.
This package name shadows utils.py, so re-export explicitly.
"""
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

_root_utils_path = Path(__file__).resolve().parent.parent / "utils.py"
_spec = spec_from_file_location("_root_utils", _root_utils_path)
_mod = module_from_spec(_spec)
if _spec and _spec.loader:
    _spec.loader.exec_module(_mod)

call_llm = getattr(_mod, "call_llm", None)
parse_json_from_llm = getattr(_mod, "parse_json_from_llm", None)

__all__ = ["call_llm", "parse_json_from_llm"]
