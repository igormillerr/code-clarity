"""Build current sources and run all CodeClarity acceptance checks with one command."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

PROJECT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest():
    files = sorted(p for p in (PROJECT / "src/main").rglob("*") if p.is_file())
    files += [PROJECT / "pom.xml", PROJECT / "requirements-python.txt"]
    result = hashlib.sha256()
    for path in files:
        result.update(path.relative_to(PROJECT).as_posix().encode("utf-8") + b"\0")
        result.update(path.read_bytes() + b"\0")
    return result.hexdigest()


def run(command, env, log, timeout):
    command = list(map(str, command))
    # Windows resolves the program before applying the child's PATH environment.
    command[0] = shutil.which(command[0], path=env["PATH"]) or command[0]
    log.write("$ " + subprocess.list2cmdline(command) + "\n")
    log.flush()
    completed = subprocess.run(command, cwd=PROJECT, env=env,
                               stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(f"Command exited with code {completed.returncode}; see stage log.")


def capture(command, env):
    return subprocess.check_output(command, cwd=PROJECT, env=env, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", timeout=15).strip()


def preflight(args, env, report, log):
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required.")
    report["python"] = sys.version
    report["python_executable"] = sys.executable
    required = re.search(r"^complexipy==([^\s#]+)",
                         (PROJECT / "requirements-python.txt").read_text(), re.MULTILINE).group(1)
    try:
        version = importlib.metadata.version("complexipy")
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError("Install requirements-python.txt into the interpreter running this command.") from error
    if version != required:
        raise RuntimeError(f"Expected complexipy {required}, found {version}. Install requirements-python.txt.")
    worker = runpy.run_path(str(PROJECT / "src/main/resources/python_analyzer.py"))
    engine = worker["load_cognitive_engine"]()
    reference = engine("def f():\n    return 1\n", check_script=False, no_ignore=True, with_plans=False)
    if len(reference.functions) != 1 or reference.functions[0].complexity != 0:
        raise RuntimeError("Real cognitive engine failed the preflight check.")
    report["complexipy"] = version
    if args.java_home:
        suffix = ".exe" if os.name == "nt" else ""
        if not all((args.java_home.resolve() / "bin" / (tool + suffix)).is_file() for tool in ("java", "javac")):
            raise RuntimeError("--java-home must point to a JDK containing bin/java and bin/javac.")
    for tool in ("java", "javac", "git"):
        executable = shutil.which(tool, path=env["PATH"])
        if not executable:
            raise RuntimeError(f"{tool} not found. Install JDK 21+ and Git; optionally pass --java-home.")
        output = capture([executable, "--version" if tool == "git" else "-version"], env)
        report[tool] = {"executable": executable, "version": output}
        log.write(output + "\n")
        if tool != "git":
            major = re.search(r'(?:javac\s+|version\s+")(\d+)', output)
            if not major or int(major.group(1)) < 21:
                raise RuntimeError(f"{tool} must be version 21 or newer.")
    report["git_head"] = capture(["git", "rev-parse", "HEAD"], env)
    report["worktree_dirty"] = bool(capture(["git", "status", "--porcelain"], env))
    report["source_sha256"] = source_digest()
    if args.build_backend == "maven" and not shutil.which("mvn", path=env["PATH"]):
        raise RuntimeError("Maven not found. Use --build-backend bundled for an offline build.")


def build_bundled(args, env, report, log, temporary):
    """Compile fresh application classes; reuse only the bundle's pinned dependencies."""
    bundle = (PROJECT / args.dependency_jar).resolve()
    pom = ET.parse(PROJECT / "pom.xml").getroot()
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    with ZipFile(bundle) as archive:
        for dependency in pom.findall("m:dependencies/m:dependency", ns):
            group, artifact, version = (dependency.findtext("m:" + name, namespaces=ns)
                                        for name in ("groupId", "artifactId", "version"))
            properties = archive.read(f"META-INF/maven/{group}/{artifact}/pom.properties").decode("utf-8")
            actual = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
            if actual.get("version") != version:
                raise RuntimeError(f"Bundle dependency mismatch: {group}:{artifact}, expected {version}. Use Maven.")
    report["dependency_jar"] = str(bundle)
    report["dependency_jar_sha256"] = digest(bundle)
    classes = temporary / "classes"
    classes.mkdir()
    sources = sorted((PROJECT / "src/main/java").rglob("*.java"))
    release = pom.findtext("m:properties/m:maven.compiler.release", namespaces=ns)
    # An argument file also works when a future source tree exceeds Windows command-line limits.
    arguments = temporary / "sources.txt"
    arguments.write_text("\n".join('"' + path.as_posix() + '"' for path in sources), encoding="utf-8")
    run(["javac", "--release", release, "-encoding", "UTF-8", "-cp", bundle,
         "-d", classes, "@" + str(arguments)], env, log, args.timeout)
    resources = PROJECT / "src/main/resources"
    resource_files = sorted(p for p in resources.rglob("*") if p.is_file())
    resource_names = {p.relative_to(resources).as_posix() for p in resource_files}
    output = PROJECT / "target/codeclarity-mcp.jar"
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = temporary / "codeclarity-mcp.jar"
    with ZipFile(bundle) as original, ZipFile(staged, "w", ZIP_DEFLATED) as result:
        for item in original.infolist():
            if not item.filename.startswith("dev/codeclarity/") and item.filename not in resource_names:
                result.writestr(item, original.read(item.filename))
        for path in sorted(classes.rglob("*.class")):
            result.write(path, path.relative_to(classes).as_posix())
        for path in resource_files:
            result.write(path, path.relative_to(resources).as_posix())
    shutil.copyfile(staged, output)
    log.write("Fresh sources and resources packaged with verified bundled dependency versions.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home", type=Path, help="JDK 21+ directory")
    parser.add_argument("--build-backend", choices=("auto", "maven", "bundled"), default="auto")
    parser.add_argument("--dependency-jar", type=Path, default=Path("plugin/server/codeclarity-mcp.jar"))
    parser.add_argument("--report-dir", type=Path, default=Path("target/checks"))
    parser.add_argument("--timeout", type=int, default=180, help="Timeout in seconds per command")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    target = (PROJECT / "target").resolve()
    report_dir = (PROJECT / args.report_dir).resolve()
    if not target.is_relative_to(PROJECT) or not report_dir.is_relative_to(PROJECT):
        parser.error("target and report directory must stay inside the project")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONOPTIMIZE="0")
    if args.java_home:
        home = args.java_home.resolve()
        env["JAVA_HOME"] = str(home)
        env["PATH"] = str(home / "bin") + os.pathsep + env.get("PATH", "")
    elif os.environ.get("JAVA_HOME"):
        env["PATH"] = str(Path(os.environ["JAVA_HOME"]) / "bin") + os.pathsep + env.get("PATH", "")
    backend = args.build_backend
    if backend == "auto":
        backend = "maven" if shutil.which("mvn", path=env.get("PATH")) else "bundled"
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "build_backend": backend,
              "success": False, "stages": []}
    suites = [
        ("python_unit", ["scripts/python_worker_test.py"]),
        ("metric_fixtures", ["scripts/python_metrics_spec_check.py", "--require-cognitive"]),
        ("core", ["scripts/core_test.py"]),
        ("java_metrics", ["scripts/java_metrics_test.py", "target/codeclarity-mcp.jar"]),
        ("python_mcp", ["scripts/python_smoke_test.py", "target/codeclarity-mcp.jar"]),
        ("python_matching", ["scripts/python_matching_test.py", "target/codeclarity-mcp.jar"]),
        ("java_mcp", ["scripts/smoke_test.py", "target/codeclarity-mcp.jar"]),
    ]
    # Keep logs outside target while Maven clean may remove target itself.
    with TemporaryDirectory(prefix="codeclarity-check-") as folder:
        temporary = Path(folder)

        def stage(name, action):
            print(f"RUN {name}", flush=True)
            started = time.monotonic()
            item = {"name": name, "status": "FAILED", "log": name + ".log"}
            report["stages"].append(item)
            with (temporary / item["log"]).open("w", encoding="utf-8") as log:
                try:
                    action(log)
                    item["status"] = "PASSED"
                except Exception as error:
                    item["error"] = f"{type(error).__name__}: {error}"
                    log.write("\n" + item["error"] + "\n")
                    raise
                finally:
                    item["seconds"] = round(time.monotonic() - started, 3)
                    print(f"{item['status']} {name} ({item['seconds']}s)", flush=True)

        try:
            stage("preflight", lambda log: preflight(args, env, report, log))
            if backend == "maven":
                stage("build", lambda log: run(["mvn", "--batch-mode", "clean", "package", "-DskipTests"],
                                                env, log, args.timeout))
            else:
                stage("build", lambda log: build_bundled(args, env, report, log, temporary))
            report["jar_sha256"] = digest(PROJECT / "target/codeclarity-mcp.jar")
            for name, command in suites:
                stage(name, lambda log, command=command: run([sys.executable, *command], env, log, args.timeout))
            report["success"] = True
        except Exception as error:
            print(f"Check failed: {error}", file=sys.stderr, flush=True)
        finally:
            names = {item["name"] for item in report["stages"]}
            for name in ["preflight", "build", *(name for name, _ in suites)]:
                if name not in names:
                    report["stages"].append({"name": name, "status": "NOT_RUN"})
            report["finished_utc"] = datetime.now(timezone.utc).isoformat()
            report_dir.mkdir(parents=True, exist_ok=True)
            for log in temporary.glob("*.log"):
                shutil.copyfile(log, report_dir / log.name)
            (report_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {report_dir / 'report.json'}", flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
