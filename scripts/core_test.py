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
               project / "src/test/java/dev/codeclarity/EntityMatchingTest.java"]

    def executable(name):
        return str(args.java_home / "bin" / name) if args.java_home else name

    with TemporaryDirectory(prefix="codeclarity-core-") as folder:
        root = Path(folder)
        classes = root / "classes"
        classes.mkdir()
        subprocess.run([executable("javac"), "--release", "21", "-encoding", "UTF-8",
                        "-d", str(classes), *map(str, sources)], check=True)
        subprocess.run([executable("java"), "-cp", str(classes), "dev.codeclarity.EntityMatchingTest"], check=True)
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


if __name__ == "__main__":
    main()
