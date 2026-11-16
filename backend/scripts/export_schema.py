"""Write shared/storyboard.schema.json from the Pydantic models.

The web app's TypeScript types are generated from that file (`npm run gen:types` in web/),
so the backend models stay the single source of truth.

    python backend/scripts/export_schema.py          # write it
    python backend/scripts/export_schema.py --check  # fail if it is out of date
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.storyboard import Storyboard, strict_json_schema  # noqa: E402

OUT = ROOT / "shared" / "storyboard.schema.json"


def render() -> str:
    schema = strict_json_schema(Storyboard)
    schema["title"] = "Storyboard"
    return json.dumps(schema, indent=2) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            sys.exit("shared/storyboard.schema.json is out of date: run python backend/scripts/export_schema.py")
        print("schema up to date")
    else:
        OUT.write_text(text)
        print(f"wrote {OUT.relative_to(ROOT)}")
