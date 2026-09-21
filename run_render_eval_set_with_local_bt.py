import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
repo_str = str(REPO_ROOT)
if repo_str not in sys.path:
    sys.path.insert(0, repo_str)

# Blender in this environment sees a namespace package named `blendertoolbox`
# before the local repo package. Remove it so the real package is imported.
existing = sys.modules.get("blendertoolbox")
if existing is not None and getattr(existing, "__file__", None) is None:
    del sys.modules["blendertoolbox"]

import render_eval_set


if __name__ == "__main__":
    render_eval_set.main()
