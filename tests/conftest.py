import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

# Sanitize sys.path to avoid importing from a different clone of this repo
# Some environments may have another finops-orchestrator checkout on sys.path (e.g., ~/Documents/Code/finops-orchestrator)
# which can cause circular imports and stale modules to load. Ensure only this workspace is preferred.
resolved_root = ROOT.resolve()
cleaned_sys_path = []
for p in sys.path:
    try:
        rp = Path(p).resolve()
    except Exception:
        cleaned_sys_path.append(p)
        continue
    # Drop paths that point to a different finops-orchestrator clone
    if rp != resolved_root and (rp.name == "finops-orchestrator" or rp.parent.name == "finops-orchestrator"):
        continue
    cleaned_sys_path.append(p)

sys.path[:] = cleaned_sys_path

# Prepend current workspace paths for deterministic imports
for path in (ROOT, BACKEND):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

# Purge accidentally imported modules from a different clone
# This can happen if another test (or PYTHONPATH) pulled in modules earlier
bad_prefix = str(resolved_root)
to_purge = []
for name, mod in list(sys.modules.items()):
    try:
        file_path = getattr(mod, "__file__", None)
        if not file_path:
            continue
        # If module path includes 'finops-orchestrator' but is NOT under our current workspace root, purge it
        if "finops-orchestrator" in file_path and not file_path.startswith(bad_prefix):
            # Only purge our project namespaces to be safe
            if name.split(".")[0] in {"backend", "services", "agents", "state", "config"}:
                to_purge.append(name)
    except Exception:
        continue

for name in to_purge:
    sys.modules.pop(name, None)

