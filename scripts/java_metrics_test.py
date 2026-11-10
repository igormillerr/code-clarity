"""Check numeric Java metrics against the packaged PMD implementation."""

import argparse
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jar", nargs="?", default="target/codeclarity-mcp.jar", type=Path)
    parser.add_argument("--java-home", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    jar = args.jar.resolve()

    def executable(name):
        return str(args.java_home / "bin" / name) if args.java_home else name

    with TemporaryDirectory(prefix="codeclarity-java-metrics-") as folder:
        subprocess.run([executable("javac"), "--release", "21", "-encoding", "UTF-8", "-cp", str(jar),
                        "-d", folder, str(project / "src/test/java/dev/codeclarity/JavaMetricsTest.java")], check=True)
        subprocess.run([executable("java"), "-cp", os.pathsep.join([folder, str(jar)]),
                        "dev.codeclarity.JavaMetricsTest"], check=True)


if __name__ == "__main__":
    main()
