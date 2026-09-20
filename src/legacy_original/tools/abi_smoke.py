from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: abi_smoke.py <bundled-internal-root>")
    root = Path(sys.argv[1]).resolve()
    # Keep the venv's standard library and site-packages ahead of the extracted
    # legacy bundle.  The original bundle contains frozen stdlib modules such
    # as ``ctypes``; putting it at sys.path[0] makes the venv interpreter load
    # those stale files and can crash before the native ABI is exercised.
    sys.path.append(str(root))
    handles = []
    for directory in (root, root / "numpy.libs"):
        if hasattr(os, "add_dll_directory") and directory.is_dir():
            handles.append(os.add_dll_directory(str(directory)))

    import cv2
    import numpy as np
    import numpy.random  # noqa: F401
    import onnxruntime

    cv2.cvtColor(np.zeros((8, 8, 4), dtype=np.uint8), cv2.COLOR_BGRA2BGR)
    print("ABI_OK", np.__version__, cv2.__version__, onnxruntime.__version__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
