from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from campus_p2_core.p1_input.normalized_paper import validate_normalized_paper


def main() -> None:
    paper_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples" / "normalized_paper_demo.json"
    result = validate_normalized_paper(paper_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
