"""CodeClarity Python AST worker. Reads source as data; never imports or executes it."""

import ast
import json
import sys

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPES = (*FUNCTIONS, ast.ClassDef, ast.Lambda)
THRESHOLD = 10


def signature(node, owners):
    args = node.args
    parameters = [arg.arg for arg in args.posonlyargs]
    if args.posonlyargs:
        parameters.append("/")
    parameters.extend(arg.arg for arg in args.args)
    if args.vararg:
        parameters.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parameters.append("*")
    parameters.extend(arg.arg for arg in args.kwonlyargs)
    if args.kwarg:
        parameters.append("**" + args.kwarg.arg)
    return ".".join([*owners, node.name]) + "(" + ", ".join(parameters) + ")"


def declarations(tree, owners=()):
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, FUNCTIONS):
            yield child, signature(child, owners)
            yield from declarations(child, (*owners, child.name))
        elif isinstance(child, ast.ClassDef):
            yield from declarations(child, (*owners, child.name))
        else:
            yield from declarations(child, owners)


def source_range(node):
    return {"startLine": min([node.lineno, *(d.lineno for d in node.decorator_list)]),
            "endLine": node.end_lineno}


def body_nodes(node):
    """Exclude nested scopes: each named function is analyzed separately."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, SCOPES):
            continue
        yield child
        yield from body_nodes(child)


def complexity(function):
    score = 1
    for statement in function.body:
        for node in [statement, *body_nodes(statement)] if not isinstance(statement, SCOPES) else []:
            if isinstance(node, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.Assert)):
                score += 1
            elif isinstance(node, ast.BoolOp):
                score += len(node.values) - 1
            elif isinstance(node, ast.comprehension):
                score += 1 + len(node.ifs)
            elif isinstance(node, ast.match_case):
                # An unguarded capture/wildcard is the default branch.
                if not (isinstance(node.pattern, ast.MatchAs) and node.pattern.pattern is None and node.guard is None):
                    score += 1
                if node.guard is not None:
                    score += 1
    return score


def abbreviated(node, source):
    text = ast.get_source_segment(source, node) or ast.unparse(node)
    return text if len(text) <= 200 else text[:199] + "\u2026"


def context(function, key, source):
    calls = []

    def walk(node, guards):
        if isinstance(node, SCOPES):
            return
        if isinstance(node, ast.Call):
            calls.append({"line": node.lineno, "expression": abbreviated(node, source), "enclosingIfs": guards})
        if isinstance(node, ast.If):
            walk(node.test, guards)
            condition = abbreviated(node.test, source)
            for branch, statements in (("then", node.body), ("else", node.orelse)):
                nested = [*guards, {"line": node.lineno, "condition": condition, "branch": branch}]
                for statement in statements:
                    walk(statement, nested)
        else:
            for child in ast.iter_child_nodes(node):
                walk(child, guards)

    for statement in function.body:
        walk(statement, [])
    calls.sort(key=lambda call: call["line"])
    return {"signature": key, "lines": source_range(function), "calls": calls[:100], "truncated": len(calls) > 100}


def handle(request):
    if sys.version_info < (3, 10):
        raise ValueError("Python 3.10 or newer is required.")
    source = request["source"]
    tree = ast.parse(source, filename=request["path"])
    functions = list(declarations(tree))
    if request["operation"] == "inspect":
        candidates = [(node, key) for node, key in functions
                      if source_range(node)["startLine"] <= request["line"] <= node.end_lineno]
        if not candidates:
            raise ValueError("No Python function or method contains line " + str(request["line"]) + ".")
        candidates.sort(key=lambda pair: pair[0].end_lineno - source_range(pair[0])["startLine"])
        if len(candidates) > 1 and source_range(candidates[0][0]) == source_range(candidates[1][0]):
            raise ValueError("Multiple declarations share that line.")
        return {"context": context(*candidates[0], source)}
    if request["operation"] != "analyze":
        raise ValueError("Unknown operation.")
    entities, findings, metrics = [], [], []
    for node, key in functions:
        entities.append({"signature": key, "lines": source_range(node)})
        score = complexity(node)
        for metric_id, algorithm, status, value, reason in (
                ("cyclomatic_complexity", "codeclarity/python-cyclo/v1", "AVAILABLE", score, None),
                ("cognitive_complexity", "unsupported", "UNSUPPORTED", None, "Not implemented for Python.")):
            metrics.append({"entity": key, "metric": {
                "definition": {"id": metric_id, "language": "python", "analyzer": "codeclarity-python-ast/1",
                               "algorithm": algorithm}, "status": status, "value": value, "reason": reason}})
        if score >= THRESHOLD:
            findings.append({"rule": "PythonCyclomaticComplexity", "line": node.lineno,
                             "column": node.col_offset + 1,
                             "message": f"Function {key} has cyclomatic complexity {score} (threshold {THRESHOLD})."})
    return {"analysis": {"entities": entities, "findings": findings, "complete": True, "warnings": [], "metrics": metrics}}


if __name__ == "__main__":
    try:
        result = handle(json.load(sys.stdin))
    except (SyntaxError, ValueError, RecursionError) as error:
        result = {"error": str(error)}
    print(json.dumps(result, ensure_ascii=True))
