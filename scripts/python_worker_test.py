"""Unit checks for the Python AST worker; requires only the standard library."""

from pathlib import Path
import json
import runpy
import sys
import unittest

WORKER = runpy.run_path(str(Path(__file__).resolve().parents[1] / "src/main/resources/python_analyzer.py"))


class WorkerTest(unittest.TestCase):
    def analyze(self, source):
        return WORKER["handle"]({"operation": "analyze", "path": "example.py", "source": source})["analysis"]

    def inspect(self, source, line):
        return WORKER["handle"]({"operation": "inspect", "path": "example.py", "source": source,
                                 "line": line})["context"]

    def metrics(self, source, target="f"):
        return {m["metric"]["definition"]["id"]: m["metric"] for m in self.analyze(source)["metrics"]
                if m["entity"].split("(")[0] == target}

    def test_specification_five_implemented_metrics(self):
        fixture = Path(__file__).resolve().parents[1] / "docs/fixtures/python_metrics_v1.json"
        for case in json.loads(fixture.read_text(encoding="utf-8"))["cases"]:
            with self.subTest(case=case["id"]):
                metrics = self.metrics(case["source"], case["target"])
                for name, expected in case["expected"].items():
                    if name != "cognitive_complexity":
                        self.assertEqual(metrics[name]["status"], "AVAILABLE")
                        self.assertEqual(metrics[name]["value"], expected, name)

    def test_sloc_parenthesized_docstrings_and_literal_tokens(self):
        source = ('def f():\n    (\n        "doc"\n        "continued"\n    ); # doc only\n'
                  '    text = "# literal"  # actual comment\n    "not a docstring"\n    return text\n')
        self.assertEqual(self.metrics(source)["function_sloc"]["value"], 4)
        self.assertEqual(self.metrics('def f():\n    "doc"; return 1\n')["function_sloc"]["value"], 2)
        self.assertEqual(self.metrics('def f():\n    "doc";\n')["function_sloc"]["value"], 1)

    def test_sloc_unicode_offsets_and_literal_line_separators(self):
        source = 'def f():\n    "описание"; value = "\u2028"\n    return value\n'
        self.assertEqual(self.metrics(source)["function_sloc"]["value"], 3)
        self.assertEqual(self.metrics('def f():\n    return f"{1 if True else 0}"\n')["function_sloc"]["value"], 2)

    def test_sloc_excludes_nested_docstrings_but_includes_nested_code(self):
        source = ('def f():\n    "outer doc"\n    class Local:\n        "class doc"\n'
                  '        def method(self):\n            "method doc"\n            return 1\n    return Local\n')
        self.assertEqual(self.metrics(source)["function_sloc"]["value"], 5)
        self.assertEqual(self.metrics(source)["return_count"]["value"], 1)
        self.assertEqual(self.metrics(source, "f.Local.method")["function_sloc"]["value"], 2)

    def test_parenthesized_multiline_decorator_range(self):
        source = '@(\n    decorate\n)\ndef f():\n    pass\n'
        self.assertEqual(self.metrics(source)["function_sloc"]["value"], 5)
        self.assertEqual(self.analyze(source)["entities"][0]["lines"]["startLine"], 1)
        self.assertEqual(self.inspect(source, 1)["signature"], "f()")

    def test_line_endings_do_not_change_metrics(self):
        source = 'def f(x):\n    "doc"\n    if x:\n        return x\n    return None\n'
        expected = self.metrics(source)
        for ending in ("\r\n", "\r"):
            with self.subTest(ending=repr(ending)):
                self.assertEqual(self.metrics(source.replace("\n", ending)), expected)

    def test_depth_distinguishes_elif_and_nested_else_if(self):
        source = 'def f(x):\n    if x:\n        pass\n    elif y:\n        pass\n    else:\n        if z:\n            pass\n'
        self.assertEqual(self.metrics(source)["max_nesting_depth"]["value"], 2)

    def test_depth_parallel_try_and_loop_branches(self):
        source = ('def f(xs):\n    try:\n        pass\n    except ValueError:\n        pass\n'
                  '    else:\n        pass\n    finally:\n        pass\n'
                  '    for x in xs:\n        pass\n    else:\n        pass\n')
        self.assertEqual(self.metrics(source)["max_nesting_depth"]["value"], 1)

    def test_depth_comprehension_expressions_and_with_items(self):
        source = 'def f(xs):\n    with a, b:\n        return [1 if x else 0 for x in xs for y in xs if y]\n'
        self.assertEqual(self.metrics(source)["max_nesting_depth"]["value"], 4)
        source = 'def f(xs):\n    return [[y for y in x] for x in xs]\n'
        self.assertEqual(self.metrics(source)["max_nesting_depth"]["value"], 2)

    def test_header_and_nested_scopes_do_not_add_body_metrics(self):
        source = ('@decorate(1 if flag else 0)\ndef f(x=1 if flag else 0):\n'
                  '    def nested():\n        if flag:\n            return 1\n'
                  '    callback = lambda x: 1 if x else 0\n    return callback\n')
        metrics = self.metrics(source)
        self.assertEqual(metrics["max_nesting_depth"]["value"], 0)
        self.assertEqual(metrics["return_count"]["value"], 1)
        self.assertEqual(metrics["parameter_count"]["value"], 1)

    def test_parameters_include_receivers_and_empty_keyword_separator(self):
        source = ('class C:\n    def f(self, /, a=1, *, b=2):\n        pass\n'
                  '    @classmethod\n    def g(cls, *args, **kwargs):\n        pass\n')
        self.assertEqual(self.metrics(source, "C.f")["parameter_count"]["value"], 3)
        self.assertEqual(self.metrics(source, "C.g")["parameter_count"]["value"], 3)

    def test_return_count_includes_unreachable_and_bare_returns(self):
        source = 'def f():\n    return\n    if False:\n        return 1\n'
        self.assertEqual(self.metrics(source)["return_count"]["value"], 2)
        self.assertEqual(self.metrics('def f(xs):\n    yield from xs\n')["return_count"]["value"], 0)

    @unittest.skipUnless(sys.version_info >= (3, 11), "except* requires Python 3.11+")
    def test_except_star_depth(self):
        source = 'def f():\n    try:\n        pass\n    except* ValueError:\n        if flag:\n            pass\n'
        self.assertEqual(self.metrics(source)["max_nesting_depth"]["value"], 2)

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
