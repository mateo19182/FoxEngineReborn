from __future__ import annotations

import json
import sys
from pathlib import Path

from foxengine.main import create_app


def _default_output_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "docs" / "openapi.json"


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else _default_output_path()
    app = create_app()
    spec = app.openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
