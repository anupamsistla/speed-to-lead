"""Write the API's OpenAPI schema to web/openapi.json (the source for the typed client).

python scripts/export_openapi.py          # write
python scripts/export_openapi.py --check  # exit 1 if the committed file is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leadagent.server import Settings, create_app  # noqa: E402

TARGET = ROOT / "web" / "openapi.json"


def build() -> str:
    app = create_app(Settings(database_path=":memory:", adapter_env={}), load_env=False)
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    fresh = build()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text() != fresh:
            print("web/openapi.json is out of date. Run: python scripts/export_openapi.py")
            return 1
        return 0
    TARGET.parent.mkdir(exist_ok=True)
    TARGET.write_text(fresh)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
