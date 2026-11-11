"""Prepare one mixed Java/Python demo from existing LLM evaluation fixtures."""
import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from llm_evals import EVALS, prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="codeclarity-llm-demo-") as staging:
        staging = Path(staging)
        for case in ("java-complexity", "python-naming"):
            for side in ("before", "after"):
                shutil.copytree(EVALS / "fixtures" / case / side, staging / side, dirs_exist_ok=True)
        manifest = prepare({"id": "mixed-demo", "kind": "code-review", "fixture": str(staging),
                            "languages": ["java", "python"],
                            "request": "Use CodeClarity readability-review for committed Java/Python changes main..HEAD; save JSON and Markdown."}, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
