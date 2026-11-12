"""Exercise history path containment and atomic storage through independent MCP JVMs."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time

from history_test import review_fixture
from python_smoke_test import close
from smoke_test import Client, git


def connect(jar, root, classes):
    command = ["java", "-jar", str(jar)] if classes is None else [
        "java", "-cp", os.pathsep.join([str(classes), str(jar)]), "dev.codeclarity.Main"]
    process = subprocess.Popen(command + ["--repo-root", str(root)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True, encoding="utf-8",
                               env=dict(os.environ, CODECLARITY_PYTHON=os.sys.executable))
    try:
        client = Client(process)
        client.send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                   "clientInfo": {"name": "storage-test", "version": "1"}})
        client.send("notifications/initialized", notification=True)
        return process, client
    except BaseException:
        process.kill()
        process.wait()
        raise


def repository(parent, name):
    root = parent / name
    root.mkdir()
    git(root, "init", "-b", "main")
    return root


def redirected_path(link, target):
    if os.name == "nt":
        # NTFS junctions need no symlink privilege and are not isSymbolicLink in Java.
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "New-Item -ItemType Junction -Path $env:CODECLARITY_TEST_LINK "
                        "-Target $env:CODECLARITY_TEST_TARGET -ErrorAction Stop | Out-Null"],
                       env=dict(os.environ, CODECLARITY_TEST_LINK=str(link),
                                CODECLARITY_TEST_TARGET=str(target)), check=True,
                       capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)
    assert link.resolve() == target.resolve()


def path_containment(jar, parent, classes):
    for index, relative in enumerate((".codeclarity", ".codeclarity/review-history.json",
                                      ".codeclarity/review-history.lock")):
        root = repository(parent, f"redirect-{index}")
        outside = parent / f"outside-{index}"
        outside.mkdir()
        marker = outside / "untouched.txt"
        marker.write_bytes(b"outside repository")
        link = root / relative
        link.parent.mkdir(exist_ok=True)
        redirected_path(link, outside)
        try:
            process, client = connect(jar, root, classes)
            try:
                client.tool("get_review_history", {}, error=True)
                client.tool("update_review_history", {"review": review_fixture(root)}, error=True)
                assert marker.read_bytes() == b"outside repository"
                assert {entry.name for entry in outside.iterdir()} == {marker.name}, relative
            finally:
                close(process)
        finally:
            # Remove just the verified redirect, never recursively traverse its target.
            assert link.resolve() == outside.resolve()
            if os.name == "nt":
                link.rmdir()
            else:
                link.unlink()


def assert_snapshot(snapshot):
    assert snapshot["statistics"]["reviewCount"] == len(snapshot["reviews"]), snapshot
    assert snapshot["statistics"]["occurrenceCount"] == len(snapshot["findings"]), snapshot
    assert len({review["reviewId"] for review in snapshot["reviews"]}) == len(snapshot["reviews"])
    assert len({finding["findingId"] for finding in snapshot["findings"]}) == len(snapshot["findings"])


def storage_transactions(jar, parent, classes):
    root = repository(parent, "transactions")
    history = root / ".codeclarity/review-history.json"
    process, client = connect(jar, root, classes)
    try:
        assert client.tool("get_review_history", {})["revision"] == 0
        assert not history.parent.exists(), "An empty read must not create storage."
        client.tool("update_review_history", {"review": review_fixture(root, 1)})
        original = history.read_bytes()

        # A raw Windows reader does not use the MCP lock and can briefly deny rename.
        # Replacement must still be atomic, and retry rather than fail or truncate.
        with ThreadPoolExecutor(max_workers=1) as pool:
            with history.open("rb") as external_reader:
                pending = pool.submit(client.tool, "update_review_history", {"review": review_fixture(root, 2)})
                if os.name == "nt":
                    deadline = time.monotonic() + 10
                    while not pending.done() and not list(history.parent.glob("review-history-*.tmp")):
                        assert time.monotonic() < deadline, "Writer did not reach atomic replacement."
                        time.sleep(0.005)
                    assert not pending.done(), "Writer replaced history while the external reader was open."
                time.sleep(0.15)
                assert external_reader.read() == original, "Replacement changed the open old snapshot."
            assert pending.result()["status"] == "saved"
        saved = history.read_bytes()
        assert len(json.loads(saved)["reviews"]) == 2

        for corrupt in (b"{invalid json", saved + b" {}"):
            history.write_bytes(corrupt)
            client.tool("get_review_history", {}, error=True)
            client.tool("update_review_history", {"review": review_fixture(root, 3)}, error=True)
            assert history.read_bytes() == corrupt, "Corrupt history must not be overwritten."
            assert not list(history.parent.glob("review-history-*.tmp"))
        history.write_bytes(saved)

        done, ready = Event(), Event()
        reader_errors, snapshots, accepted = [], [], []

        def reader():
            reader_process = None
            try:
                reader_process, reader_client = connect(jar, root, classes)
                while not done.is_set():
                    snapshot = reader_client.tool("get_review_history", {})
                    assert_snapshot(snapshot)
                    snapshots.append(snapshot["revision"])
                    ready.set()
            except BaseException as error:
                reader_errors.append(repr(error))
                ready.set()
            finally:
                if reader_process is not None:
                    close(reader_process)

        def writer(worker):
            writer_process, writer_client = connect(jar, root, classes)
            try:
                for offset in range(3):
                    review = review_fixture(root, 100 + worker * 3 + offset)
                    receipt = writer_client.tool("update_review_history", {"review": review})
                    assert receipt["status"] == "saved", receipt
                    accepted.append(review["reviewId"])
                    replay = writer_client.tool("update_review_history", {"review": review})
                    assert replay["status"] == "unchanged", replay
            finally:
                close(writer_process)

        thread = Thread(target=reader)
        thread.start()
        try:
            assert ready.wait(timeout=45), "MCP reader did not start."
            assert not reader_errors, reader_errors
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(writer, range(4)))
        finally:
            done.set()
            thread.join(timeout=50)
        assert not thread.is_alive(), "MCP reader did not stop."
        assert not reader_errors and snapshots, reader_errors
        final = client.tool("get_review_history", {})
        assert_snapshot(final)
        assert len(accepted) == 12 and len(set(accepted)) == 12
        assert {review["reviewId"] for review in final["reviews"]} == {
            "storage-review-1", "storage-review-2", *accepted}, "Accepted events were lost."
        assert final["revision"] == 14, final["revision"]
        assert json.loads(history.read_bytes()) == final
        assert not list(history.parent.glob("review-history-*.tmp"))
        return len(snapshots), len(accepted)
    finally:
        close(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jar", nargs="?", type=Path, default=Path("target/codeclarity-mcp.jar"))
    parser.add_argument("--classes", type=Path, help="Optional isolated compiled storage override for development.")
    args = parser.parse_args()
    jar = args.jar.resolve()
    classes = args.classes.resolve() if args.classes else None
    with TemporaryDirectory(prefix="codeclarity-history-storage-") as directory:
        parent = Path(directory)
        path_containment(jar, parent, classes)
        reads, writes = storage_transactions(jar, parent, classes)
    print(f"Passed: redirected directory/history/lock rejected, corrupt bytes preserved, "
          f"atomic replacement with an external reader, {reads} consistent MCP reads and "
          f"{writes} accepted concurrent writes plus idempotent replays without lost data.")


if __name__ == "__main__":
    main()
