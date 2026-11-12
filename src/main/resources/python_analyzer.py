"""CodeClarity Python AST worker. Reads source as data; never imports or executes it."""

import ast
import bisect
import io
import importlib.metadata
import json
import sys
import tokenize
from collections import Counter

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPES = (*FUNCTIONS, ast.ClassDef, ast.Lambda)
THRESHOLD = 10
TRY_NODES = (ast.Try,) + ((ast.TryStar,) if hasattr(ast, "TryStar") else ())
COGNITIVE_VERSION = "8.3.0"
COGNITIVE_ALGORITHM = "codeclarity/python-function-scope/v1;no_ignore=true;with_plans=false;check_script=false"


class SourceFacts:
    """Tokenize once per file; reuse physical code lines and elif locations."""

    def __init__(self, source, tree):
        self.lines = io.StringIO(source).readlines()
        offsets = [0]
        for line in self.lines:
            offsets.append(offsets[-1] + len(line))
        self.offsets = offsets

        def offset(line, byte_column):
            return offsets[line - 1] + self.character_column(line, byte_column)

        docstrings = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, *FUNCTIONS)) or not node.body:
                continue
            first = node.body[0]
            if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                continue
            start = offset(first.lineno, first.col_offset)
            end = offset(first.end_lineno, first.end_col_offset)
            # A separator after a docstring is not a separate statement of code.
            separator = end
            while separator < len(source) and source[separator] in " \t":
                separator += 1
            if separator < len(source) and source[separator] == ";":
                end = separator + 1
            docstrings.append((start, end))

        docstrings.sort()
        docstring_starts = [start for start, _ in docstrings]

        ignored = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                   tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
        code_lines = set()
        self.elifs = set()
        decorator_tokens = []
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in ignored or not token.string:
                continue
            # Token columns are characters, whereas AST columns above are UTF-8 bytes.
            token_start = offsets[token.start[0] - 1] + token.start[1]
            index = bisect.bisect_right(docstring_starts, token_start) - 1
            if index >= 0:
                token_end = offsets[token.end[0] - 1] + token.end[1]
                if token_end <= docstrings[index][1]:
                    continue
            if token.type == tokenize.NAME and token.string == "elif":
                self.elifs.add(token.start)
            if token.type == tokenize.OP and token.string == "@":
                decorator_tokens.append(token.start)
            last_line = token.end[0] - (token.end[1] == 0 and token.end[0] > token.start[0])
            code_lines.update(range(token.start[0], last_line + 1))
        self.code_prefix = [0]
        for line in range(1, len(self.lines) + 1):
            self.code_prefix.append(self.code_prefix[-1] + (line in code_lines))
        self.decorator_lines = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, *FUNCTIONS)) and node.decorator_list:
                first = node.decorator_list[0]
                position = (first.lineno, self.character_column(first.lineno, first.col_offset))
                index = bisect.bisect_right(decorator_tokens, position) - 1
                if index >= 0:
                    self.decorator_lines[node] = decorator_tokens[index][0]

    def character_column(self, line, byte_column):
        return len(self.lines[line - 1].encode("utf-8")[:byte_column].decode("utf-8"))

    def offset(self, line, byte_column):
        return self.offsets[line - 1] + self.character_column(line, byte_column)

    def sloc(self, function):
        first = source_range(function, self)["startLine"]
        return self.code_prefix[function.end_lineno] - self.code_prefix[first - 1]


def nesting_depth(function, facts):
    def walk(node, depth):
        if isinstance(node, SCOPES):
            return depth
        if isinstance(node, ast.If):
            position = (node.lineno, facts.character_column(node.lineno, node.col_offset))
            depth += position not in facts.elifs
        elif isinstance(node, (ast.IfExp, ast.For, ast.AsyncFor, ast.While,
                               ast.With, ast.AsyncWith, ast.Match, *TRY_NODES)):
            depth += 1
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            depth += len(node.generators)
        return max([depth, *(walk(child, depth) for child in ast.iter_child_nodes(node))])

    return max([0, *(walk(statement, 0) for statement in function.body)])


def parameter_count(function):
    args = function.args
    return (len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
            + int(args.vararg is not None) + int(args.kwarg is not None))


def return_count(function):
    return sum(isinstance(node, ast.Return) for statement in function.body if not isinstance(statement, SCOPES)
               for node in (statement, *body_nodes(statement)))


def isolated_function(source, function, facts):
    """Preserve control-flow spelling; mask nested scopes without executing code."""
    edits = []

    def walk(node):
        if isinstance(node, SCOPES):
            if isinstance(node, ast.Lambda):
                start = facts.offset(node.lineno, node.col_offset)
                replacement = "None"
            else:
                line = facts.decorator_lines.get(node, node.lineno)
                start = facts.offset(line, node.col_offset)
                replacement = "pass"
            end = facts.offset(node.end_lineno, node.end_col_offset)
            edits.append((start, end, replacement))
            return
        for child in ast.iter_child_nodes(node):
            walk(child)

    for statement in function.body:
        walk(statement)
    start = facts.offset(function.lineno, function.col_offset)
    end = facts.offset(function.end_lineno, function.end_col_offset)
    # Edits preserve character offsets and newlines, including after Unicode text.
    # Never unparse the AST: that can silently rewrite else + if into elif.
    for left, right, replacement in sorted(edits, reverse=True):
        remainder = "".join("\n" if char == "\n" else " "
                            for char in source[left + len(replacement):right])
        source = source[:left] + replacement + remainder + source[right:]
    return source[start:end]


def load_cognitive_engine():
    version = importlib.metadata.version("complexipy")
    if version != COGNITIVE_VERSION:
        raise ValueError(f"Expected complexipy {COGNITIVE_VERSION}, found {version}.")
    from complexipy import code_complexity
    return code_complexity


def cognitive_value(engine, source, function, facts):
    result = engine(isolated_function(source, function, facts),
                    check_script=False, no_ignore=True, with_plans=False)
    if not result.functions:
        return "MISSING", None, "complexipy returned no function measurement."
    if len(result.functions) != 1 or result.functions[0].name != function.name:
        return "ERROR", None, "complexipy returned an ambiguous or mismatched function."
    value = result.functions[0].complexity
    if type(value) is not int or value < 0:
        return "ERROR", None, "complexipy returned an invalid complexity value."
    return "AVAILABLE", value, None


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


def ambiguous_owners(tree):
    counts = Counter()

    def walk(node, owners):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, *FUNCTIONS)):
                path = (*owners, child.name)
                counts[".".join(path)] += 1
                walk(child, path)
            else:
                walk(child, owners)

    walk(tree, ())
    return {name for name, count in counts.items() if count > 1}


def source_range(node, facts=None):
    first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    if facts is not None:
        first = facts.decorator_lines.get(node, first)
    return {"startLine": first,
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


def context(function, key, source, facts=None):
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
    return {"signature": key, "lines": source_range(function, facts), "calls": calls[:100], "truncated": len(calls) > 100}


def handle(request):
    if sys.version_info < (3, 10):
        raise ValueError("Python 3.10 or newer is required.")
    source = request["source"].replace("\r\n", "\n").replace("\r", "\n")
    tree = ast.parse(source, filename=request["path"])
    facts = SourceFacts(source, tree)
    functions = list(declarations(tree))
    if request["operation"] == "inspect":
        candidates = [(node, key) for node, key in functions
                      if source_range(node, facts)["startLine"] <= request["line"] <= node.end_lineno]
        if not candidates:
            raise ValueError("No Python function or method contains line " + str(request["line"]) + ".")
        candidates.sort(key=lambda pair: pair[0].end_lineno - source_range(pair[0], facts)["startLine"])
        if len(candidates) > 1 and source_range(candidates[0][0], facts) == source_range(candidates[1][0], facts):
            raise ValueError("Multiple declarations share that line.")
        return {"context": context(*candidates[0], source, facts)}
    if request["operation"] != "analyze":
        raise ValueError("Unknown operation.")
    entities, findings, metrics, warnings = [], [], [], []
    ambiguous = ambiguous_owners(tree)
    engine, engine_error = None, None
    if functions:
        try:
            engine = load_cognitive_engine()
        except Exception as error:
            engine_error = (f"Cognitive Complexity unavailable: {type(error).__name__}: {error} "
                            f"Install complexipy=={COGNITIVE_VERSION} in the selected Python interpreter.")
            warnings.append(engine_error)
    for node, key in functions:
        # Python identifiers cannot contain '('; the qualified name excludes parameters.
        qualified = key.partition("(")[0]
        parts = qualified.split(".")
        uncertain = any(".".join(parts[:length]) in ambiguous for length in range(1, len(parts) + 1))
        entities.append({"signature": key, "lines": source_range(node, facts), "matchingKey": qualified,
                         "matchingAmbiguous": uncertain})
        score = complexity(node)
        cognitive = ("ERROR", None, engine_error)
        if engine is not None:
            try:
                cognitive = cognitive_value(engine, source, node, facts)
            except Exception as error:
                cognitive = ("ERROR", None, f"complexipy failed: {type(error).__name__}: {error}")
            if cognitive[0] != "AVAILABLE":
                warnings.append(f"{key}: {cognitive[2]}")
        for metric_id, algorithm, status, value, reason in (
                ("cyclomatic_complexity", "codeclarity/python-cyclo/v1", "AVAILABLE", score, None),
                ("cognitive_complexity", COGNITIVE_ALGORITHM, *cognitive),
                ("function_sloc", "codeclarity/python-physical-sloc/v1", "AVAILABLE", facts.sloc(node), None),
                ("max_nesting_depth", "codeclarity/python-nesting/v1", "AVAILABLE", nesting_depth(node, facts), None),
                ("parameter_count", "codeclarity/python-parameters/include-receiver/v1", "AVAILABLE", parameter_count(node), None),
                ("return_count", "codeclarity/python-explicit-returns/v1", "AVAILABLE", return_count(node), None)):
            metrics.append({"entity": key, "metric": {
                "definition": {"id": metric_id, "language": "python",
                               "analyzer": f"complexipy/{COGNITIVE_VERSION}" if metric_id == "cognitive_complexity" else "codeclarity-python-ast/1",
                               "algorithm": algorithm}, "status": status, "value": value, "reason": reason}})
        if score >= THRESHOLD:
            findings.append({"rule": "PythonCyclomaticComplexity", "line": node.lineno,
                             "column": node.col_offset + 1,
                             "message": f"Function {key} has cyclomatic complexity {score} (threshold {THRESHOLD})."})
    # complete describes entity/finding coverage, not availability of every metric.
    # Metric-specific failures use ERROR/MISSING plus warnings, retaining other values.
    return {"analysis": {"entities": entities, "findings": findings, "complete": True, "warnings": warnings, "metrics": metrics}}


if __name__ == "__main__":
    try:
        result = handle(json.load(sys.stdin))
    except (SyntaxError, ValueError, RecursionError, tokenize.TokenError) as error:
        result = {"error": str(error)}
    print(json.dumps(result, ensure_ascii=True))
