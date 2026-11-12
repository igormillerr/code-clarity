"""Check the application worker against the six-metric specification fixtures."""

import argparse
import json
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--complexipy-path", type=Path,
                        help="Optional isolated package directory; prefer installing requirements-python.txt")
    parser.add_argument("--require-cognitive", action="store_true",
                        help="Fail unless the real cognitive metric can be verified")
    args = parser.parse_args()
    if args.complexipy_path:
        sys.path.insert(0, str(args.complexipy_path.resolve()))
    project = Path(__file__).resolve().parents[1]
    data = json.loads((project / "docs/fixtures/python_metrics_v1.json").read_text(encoding="utf-8"))
    worker = runpy.run_path(str(project / "src/main/resources/python_analyzer.py"))
    try:
        worker["load_cognitive_engine"]()
        cognitive_available = True
    except Exception as error:
        cognitive_available = False
        if args.require_cognitive:
            parser.error(f"Cognitive engine unavailable: {error}")
    for item in data["cases"]:
        compile(item["source"], item["id"], "exec", dont_inherit=True)
        assert len(item["expected"]) == 6 and all(type(v) is int and v >= 0 for v in item["expected"].values()), item["id"]
        result = worker["handle"](dict(operation="analyze", path="fixture.py", source=item["source"]))["analysis"]
        measurements = {m["metric"]["definition"]["id"]: m["metric"] for m in result["metrics"]
                        if m["entity"].split("(")[0] == item["target"]}
        for name, expected in item["expected"].items():
            if name == "cognitive_complexity" and not cognitive_available:
                assert measurements[name]["status"] == "ERROR", (item["id"], name)
                continue
            assert measurements[name]["status"] == "AVAILABLE", (item["id"], name, measurements[name])
            assert measurements[name]["value"] == expected, (item["id"], name, measurements[name]["value"], expected)
    count = 6 if cognitive_available else 5
    print(f"Passed: {len(data['cases'])} syntax checks and {count} application metric values per case.")
    if not cognitive_available:
        print("Cognitive values not verified: install requirements-python.txt and use --require-cognitive.")


if __name__ == "__main__":
    main()
