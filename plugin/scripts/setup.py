"""Validate CodeClarity prerequisites and configure this user's selected repository/Python.

Uses only Python's standard library. Does not install packages or change Codex settings.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


REQUIRED_COMPLEXIPY = "8.3.0"


class SetupError(Exception):
    pass


def run(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SetupError(f"Cannot run {command[0]}: {error}") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1500:]
        raise SetupError(f"Command failed ({command[0]}): {detail}")
    return (result.stdout + result.stderr).strip()


def selector_path(value, label):
    value = os.fspath(value)
    if not value.strip() or any(char in value for char in "\r\n\0"):
        raise SetupError(f"{label} must be one nonempty path without line breaks")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SetupError(f"{label} must be an absolute path")
    # Do not resolve symlinks: venv/bin/python can point to a base interpreter.
    return Path(os.path.abspath(path))


def read_selector(config_dir, name):
    path = config_dir / name
    try:
        if path.stat().st_size > 8192:
            raise SetupError(f"{name} exceeds 8192 bytes")
        return path.read_text(encoding="utf-8-sig").strip()
    except OSError as error:
        raise SetupError(f"Missing/unreadable {path}; supply the corresponding argument") from error


def java_version(command):
    executable = shutil.which(command)
    if not executable:
        raise SetupError(f"{command} is missing from PATH; install a JDK 21+ and restart Codex")
    output = run([executable, "-version"])
    match = re.search(r'(?:version\s+"?|javac\s+)(\d+)(?:[.\s"-]|$)', output)
    if not match or int(match.group(1)) < 21:
        raise SetupError(f"{command} must be version 21+: {output}")
    return {"path": executable, "major": int(match.group(1))}


def validate(python, repo_root):
    interpreter = selector_path(python, "Python interpreter")
    if not interpreter.is_file():
        raise SetupError(f"Python interpreter does not exist: {interpreter}")
    expression = (
        "import json,sys,importlib.metadata as m; "
        "print(json.dumps({'version':list(sys.version_info[:3]),"
        "'complexipy':m.version('complexipy')}))"
    )
    try:
        info = json.loads(run([str(interpreter), "-c", expression]))
    except (ValueError, TypeError) as error:
        raise SetupError("Selected Python returned invalid version information") from error
    if tuple(info.get("version", [])) < (3, 10):
        raise SetupError("Python 3.10+ is required")
    if info.get("complexipy") != REQUIRED_COMPLEXIPY:
        raise SetupError(f"Selected Python needs complexipy=={REQUIRED_COMPLEXIPY}; "
                         "install plugin/requirements-python.txt into that interpreter")
    repo = selector_path(repo_root, "Repository")
    if not repo.is_dir():
        raise SetupError(f"Repository directory does not exist: {repo}")
    git = shutil.which("git")
    if not git:
        raise SetupError("Git is missing from PATH")
    actual_root = run([git, "-C", str(repo), "rev-parse", "--show-toplevel"])
    # A subdirectory is accepted and normalized to Git's actual worktree root.
    root = selector_path(actual_root, "Git root")
    java = java_version("java")
    javac = java_version("javac")
    if not any(line.startswith("jdk.compiler@") for line in run([java["path"], "--list-modules"]).splitlines()):
        raise SetupError("The java command must come from a full JDK; the launcher requires jdk.compiler")
    return {"python": str(interpreter), "pythonVersion": info["version"],
            "complexipy": info["complexipy"], "repoRoot": str(root),
            "java": java, "javac": javac, "git": git}


def write_selector(directory, name, value):
    payload = (value + "\n").encode("utf-8")
    if len(payload) > 8192:
        raise SetupError(f"{name} exceeds 8192 bytes")
    path = directory / name
    if path.is_symlink():
        raise SetupError(f"Refusing to replace symlink: {path}")
    if path.is_file() and path.read_bytes() == payload:
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", help="Absolute executable path in an environment with complexipy 8.3.0")
    parser.add_argument("--repo-root", help="Absolute path to the Git repository to review")
    parser.add_argument("--config-dir", type=Path, default=Path.home() / ".codeclarity",
                        help="Selector directory (default: ~/.codeclarity)")
    parser.add_argument("--check", action="store_true", help="Validate only; do not write selector files")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable result")
    args = parser.parse_args(argv)
    try:
        config = args.config_dir.expanduser().absolute()
        python = args.python or (read_selector(config, "python-path.txt") if args.check else sys.executable)
        repo = args.repo_root or read_selector(config, "repo-root.txt")
        result = validate(python, repo)
        # Check all destinations and limits before either selector is changed.
        for name, value in (("python-path.txt", result["python"]), ("repo-root.txt", result["repoRoot"])):
            if len((value + "\n").encode("utf-8")) > 8192:
                raise SetupError(f"{name} exceeds 8192 bytes")
            if (config / name).is_symlink():
                raise SetupError(f"Refusing a symlink selector: {config / name}")
        if not args.check:
            config.mkdir(parents=True, exist_ok=True)
            write_selector(config, "python-path.txt", result["python"])
            write_selector(config, "repo-root.txt", result["repoRoot"])
        result.update(status="PASS", mode="check" if args.check else "configured", configDir=str(config))
        if args.json:
            print(json.dumps(result, ensure_ascii=True, indent=2))
        else:
            print(f"CodeClarity setup: PASS ({result['mode']})")
            print(f"Repository: {result['repoRoot']}")
            print(f"Python: {result['python']} / complexipy {result['complexipy']}")
            print("JDK and Git: OK. Restart Codex/MCP after changing selectors.")
        return 0
    except (SetupError, OSError) as error:
        if args.json:
            print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=True))
        else:
            print(f"CodeClarity setup: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
