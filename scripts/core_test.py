"""Compile core without Java tooling dependencies and exercise a custom language."""

import argparse
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    base = project / "src/main/java/dev/codeclarity"
    sources = [*base.joinpath("core").rglob("*.java"), *base.joinpath("git").rglob("*.java"),
               project / "src/test/java/dev/codeclarity/CoreBoundaryTest.java",
               project / "src/test/java/dev/codeclarity/CoreRoutingTest.java"]

    def executable(name):
        return str(args.java_home / "bin" / name) if args.java_home else name

    with TemporaryDirectory(prefix="codeclarity-core-") as folder:
        root = Path(folder)
        classes = root / "classes"
        classes.mkdir()
        subprocess.run([executable("javac"), "--release", "21", "-encoding", "UTF-8",
                        "-d", str(classes), *map(str, sources)], check=True)
        repo = root / "repo"
        repo.mkdir()

        def git(*arguments):
            subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True)

        def write(path, text):
            (repo / path).write_text(text, encoding="utf-8")

        git("init", "-b", "main")
        git("config", "user.name", "Core test")
        git("config", "user.email", "core@example.test")
        write("changed.fixture", "simple\n")
        write("deleted.fixture", "simple\ncomplex\n")
        write("incoming.txt", "enter language\n")
        write("left.fixture", "leave language\n")
        write("ignored.txt", "original\n")
        git("add", ".")
        git("commit", "-m", "base")
        git("switch", "-c", "feature")
        write("changed.fixture", "complex\n")
        write("deleted.fixture", "simple\n")
        write("incomplete.fixture", "complex incomplete\n")
        write("ignored.txt", "changed\n")
        git("mv", "incoming.txt", "entered.fixture")
        git("mv", "left.fixture", "left.txt")
        git("add", ".")
        git("commit", "-m", "head")
        write("changed.fixture", "working tree must be ignored\n")
        subprocess.run([executable("java"), "-cp", str(classes), "dev.codeclarity.CoreBoundaryTest", str(repo)],
                       check=True)

        repo = root / "routing"
        repo.mkdir()
        git("init", "-b", "main")
        git("config", "user.name", "Core routing test")
        git("config", "user.email", "routing@example.test")
        for path in ("a-good.one", "z-good.two", "crash.one", "malformed.one", "incomplete.two"):
            write(path, "simple\n")
        write("cross.one", "cross language unique\n")
        write("ignored.txt", "before\n")
        git("add", ".")
        git("commit", "-m", "base")
        git("switch", "-c", "feature")
        for path, content in {"a-good.one": "complex", "z-good.two": "complex", "crash.one": "crash",
                              "malformed.one": "malformed", "incomplete.two": "incomplete"}.items():
            write(path, content + "\n")
        git("mv", "cross.one", "cross.two")
        write("oversized.one", "x" * 250001)
        write("ignored.txt", "after\n")
        git("add", ".")
        git("commit", "-m", "head")
        subprocess.run([executable("java"), "-cp", str(classes), "dev.codeclarity.CoreRoutingTest", str(repo)],
                       check=True)


if __name__ == "__main__":
    main()
