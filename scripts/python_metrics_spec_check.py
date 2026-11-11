"""Check specification fixtures and optionally the isolated complexipy reference.

Structural metric numbers are acceptance targets, not verified implementations.
This script does not execute fixture code or change the application analyzer.
"""
import argparse
import ast
import importlib.metadata
import json
from pathlib import Path
import runpy
import sys

def functions(tree, owners=()):
    for child in ast.iter_child_nodes(tree):
        if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)):
            yield ".".join((*owners,child.name)),child
            yield from functions(child,(*owners,child.name))
        elif isinstance(child,ast.ClassDef): yield from functions(child,(*owners,child.name))
        else: yield from functions(child,owners)

def isolate(source, root):
    lines=source.splitlines(keepends=True)
    def offset(line, byte_column):
        return sum(map(len,lines[:line-1]))+len(lines[line-1].encode("utf-8")[:byte_column].decode("utf-8"))
    def span(node):
        start=offset(node.lineno,node.col_offset)
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and node.decorator_list:
            decorator=node.decorator_list[0]
            start=offset(decorator.lineno,decorator.col_offset-1)
        return start,offset(node.end_lineno,node.end_col_offset)
    edits=[]
    def walk(node):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):
            start,end=span(node)
            edits.append((start,end,"None" if isinstance(node,ast.Lambda) else "pass"))
        else:
            for child in ast.iter_child_nodes(node): walk(child)
    for statement in root.body: walk(statement)
    start,end=offset(root.lineno,root.col_offset),offset(root.end_lineno,root.end_col_offset)
    for a,b,replacement in sorted(edits,reverse=True):
        remainder="".join("\n" if c=="\n" else " " for c in source[a+len(replacement):b])
        source=source[:a]+replacement+remainder+source[b:]
    return source[start:end]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--complexipy-path",type=Path,help="Directory with experimental complexipy 8.3.0 installation")
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]
    data=json.loads((project / "docs/fixtures/python_metrics_v1.json").read_text(encoding="utf-8"))
    worker=runpy.run_path(str(project / "src/main/resources/python_analyzer.py"))
    for item in data["cases"]:
        compile(item["source"],item["id"],"exec",dont_inherit=True)
        assert len(item["expected"])==6 and all(type(value) is int and value>=0 for value in item["expected"].values()),item["id"]
        result=worker["handle"](dict(operation="analyze",path="fixture.py",source=item["source"]))["analysis"]
        measurements=[m["metric"]["value"] for m in result["metrics"]
                      if m["entity"].split("(")[0]==item["target"] and m["metric"]["definition"]["id"]=="cyclomatic_complexity"]
        assert measurements==[item["expected"]["cyclomatic_complexity"]],item["id"]
    print(f"Passed: {len(data['cases'])} fixture syntax checks and existing CC values. Structural expectations await implementation.")
    if args.complexipy_path:
        sys.path.insert(0,str(args.complexipy_path.resolve()))
        assert importlib.metadata.version("complexipy")==data["cognitive_reference"]["version"],"Reference version mismatch"
        from complexipy import code_complexity
        for item in data["cases"]:
            root=dict(functions(ast.parse(item["source"])))[item["target"]]
            source=isolate(item["source"],root)
            result=code_complexity(source,check_script=False,no_ignore=True,with_plans=False)
            assert len(result.functions)==1,item["id"]
            assert result.functions[0].complexity==item["expected"]["cognitive_complexity"],item["id"]
        print("Passed: 20 cognitive reference values using complexipy 8.3.0 with source-preserving scope isolation.")
    else:
        print("Cognitive reference not run: pass --complexipy-path to check the experimental dependency.")

if __name__=="__main__":
    main()
