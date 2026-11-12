"""Prepare disposable review scopes from existing LLM or Python-team fixtures."""
import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from llm_evals import EVALS, prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", choices=("llm-fixtures", "python-experiments"), default="llm-fixtures")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="codeclarity-llm-demo-") as staging:
        staging = Path(staging)
        if args.source == "python-experiments":
            for side in ("before", "after"):
                (staging / side).mkdir()
                for case in ("structure", "naming"):
                    source = EVALS.parent / "experiments/python_readability" / case / (side + ".py")
                    shutil.copyfile(source, staging / side / (case + ".py"))
            scenario_id, languages = "python-team-demo", ["python"]
        else:
            for case in ("java-complexity", "python-naming"):
                for side in ("before", "after"):
                    shutil.copytree(EVALS / "fixtures" / case / side, staging / side, dirs_exist_ok=True)
            scenario_id, languages = "mixed-demo", ["java", "python"]
        manifest = prepare({"id": scenario_id, "kind": "code-review", "fixture": str(staging),
                            "languages": languages,
                            "request": "Use CodeClarity readability-review for committed changes main..HEAD in the selected languages; save JSON and Markdown."}, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
