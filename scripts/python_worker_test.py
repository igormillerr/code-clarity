"""Unit checks for the Python AST worker; requires only the standard library."""

from pathlib import Path
import runpy
import unittest

WORKER = runpy.run_path(str(Path(__file__).resolve().parents[1] / "src/main/resources/python_analyzer.py"))


class WorkerTest(unittest.TestCase):
    def analyze(self, source):
        return WORKER["handle"]({"operation": "analyze", "path": "example.py", "source": source})["analysis"]

    def inspect(self, source, line):
        return WORKER["handle"]({"operation": "inspect", "path": "example.py", "source": source,
                                 "line": line})["context"]

    def test_scopes_and_decorators(self):
        source = ("@decorate()\nasync def outer(a, /, b=1, *, c=2, **kw):\n"
                  "    def inner():\n        return nested()\n    return outside()\n"
                  "class Service:\n    def method(self):\n        return call()\n")
        entities = self.analyze(source)["entities"]
        self.assertEqual([e["signature"] for e in entities],
                         ["outer(a, /, b, *, c, **kw)", "outer.inner()", "Service.method(self)"])
        self.assertEqual(entities[0]["lines"], {"startLine": 1, "endLine": 5})
        self.assertEqual([c["expression"] for c in self.inspect(source, 1)["calls"]], ["outside()"])
        self.assertEqual(self.inspect(source, 4)["signature"], "outer.inner()")

    def test_then_else_and_condition_calls(self):
        source = "def f():\n    if check():\n        if ready:\n            send()\n    else:\n        stop()\n"
        calls = {c["expression"]: c for c in self.inspect(source, 1)["calls"]}
        self.assertEqual(calls["check()"]["enclosingIfs"], [])
        self.assertEqual([g["branch"] for g in calls["send()"]["enclosingIfs"]], ["then", "then"])
        self.assertEqual(calls["stop()"]["enclosingIfs"][0]["branch"], "else")

    def test_complexity_and_nested_scope_isolation(self):
        source = "def outer():\n    def inner():\n" + "        if flag: pass\n" * 9 + "    return 1\n"
        findings = self.analyze(source)["findings"]
        self.assertEqual(len(findings), 1)
        self.assertIn("outer.inner() has cyclomatic complexity 10", findings[0]["message"])
        self.assertEqual(self.analyze("def f():\n" + "    if x: pass\n" * 8)["findings"], [])

    def test_decision_constructs(self):
        tree = WORKER["ast"].parse("def f(xs):\n    assert xs\n    if a and b or c: pass\n"
                                    "    for x in xs:\n        while x: break\n"
                                    "    try: pass\n    except ValueError: pass\n"
                                    "    ys = [x for x in xs if x]\n    return 1 if xs else 0\n")
        self.assertEqual(WORKER["complexity"](tree.body[0]), 11)
        tree = WORKER["ast"].parse("def f(x):\n    match x:\n        case 1: pass\n"
                                    "        case y if y: pass\n        case _: pass\n")
        self.assertEqual(WORKER["complexity"](tree.body[0]), 4)

    def test_limits_and_unicode(self):
        result = self.inspect("def f():\n" + "    send('Привет')\n" * 101, 1)
        self.assertEqual(len(result["calls"]), 100)
        self.assertTrue(result["truncated"])
        result = self.inspect("def f():\n    send('" + "x" * 250 + "')\n", 1)
        self.assertEqual(len(result["calls"][0]["expression"]), 200)

    def test_parse_errors_and_no_code_execution(self):
        with self.assertRaises(SyntaxError):
            self.analyze("def broken(:")
        self.assertEqual(self.analyze("raise RuntimeError('must not execute')\n")["entities"], [])
        with self.assertRaises(ValueError):
            self.inspect("x = 1\n", 1)

    def test_numeric_metrics_below_threshold_and_unsupported(self):
        result = self.analyze("def f():\n    if flag: pass\n")
        self.assertEqual(result["findings"], [])
        values = {m["metric"]["definition"]["id"]: m["metric"] for m in result["metrics"]}
        self.assertEqual(values["cyclomatic_complexity"]["value"], 2)
        self.assertEqual(values["cyclomatic_complexity"]["status"], "AVAILABLE")
        self.assertEqual(values["cognitive_complexity"]["status"], "UNSUPPORTED")
        self.assertIsNone(values["cognitive_complexity"]["value"])


if __name__ == "__main__":
    unittest.main()
