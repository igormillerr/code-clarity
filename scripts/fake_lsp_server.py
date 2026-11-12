"""Controlled LSP peer for transport failure/cleanup tests. Not a JDT LS replacement."""
import json
from pathlib import Path
import os
import sys
import time

mode, pid_path = sys.argv[1:3]
Path(pid_path).write_text(str(os.getpid()))


def send(value):
    data = json.dumps(value, ensure_ascii=False).encode()
    header = f"Content-Length: {len(data)}\r\n\r\n".encode()
    # Fragmented UTF-8 messages exercise byte framing, not line-oriented JSON.
    for part in (header[:7], header[7:], data[:9], data[9:]):
        sys.stdout.buffer.write(part)
        sys.stdout.buffer.flush()


def read():
    header = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line: raise EOFError()
        if line == b"\r\n": break
        key, value = line.decode().split(":", 1)
        header[key.lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(header["content-length"])))


document = None
init_id = None
try:
    while True:
        message = read()
        method = message.get("method")
        if method == "initialize":
            if mode == "hang-init": time.sleep(30)
            if mode == "eof": sys.exit(3)
            init_id = message["id"]
            send({"jsonrpc": "2.0", "id": 700, "method": "workspace/configuration",
                  "params": {"items": [{"section": "java"}, {"section": "java.import.gradle.enabled"}]}})
        elif message.get("id") == 700:
            assert message["result"][0]["autobuild"]["enabled"] is False
            assert message["result"][0]["project"]["sourcePaths"] == ["src/main/java", "src/test/java"]
            assert message["result"][1] is False
            send({"jsonrpc": "2.0", "id": init_id, "result": {"capabilities": {
                "definitionProvider": True, "referencesProvider": True, "positionEncoding": "utf-16"}}})
        elif method == "initialized":
            send({"jsonrpc": "2.0", "method": "language/status", "params": {"type": "ServiceReady", "message": "Готов 🚀"}})
            if mode == "hang-write": time.sleep(30)
        elif method == "textDocument/didOpen":
            if mode == "stateful":
                assert document is None, "Document requests overlapped or previous document was not closed"
                with Path(pid_path + ".documents").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(message["params"]["textDocument"], ensure_ascii=False) + "\n")
            document = message["params"]["textDocument"]
        elif method == "textDocument/didClose":
            if mode == "stateful":
                assert document is not None and document["uri"] == message["params"]["textDocument"]["uri"]
            document = None
        elif method in ("textDocument/definition", "textDocument/references"):
            if mode == "stateful": time.sleep(0.02)
            if mode == "hang-request": time.sleep(30)
            if mode == "malformed":
                sys.stdout.buffer.write(b"Content-Length: 999999999\r\n\r\n")
                sys.stdout.buffer.flush()
                continue
            if mode == "stderr":
                sys.stderr.write("diagnostics\n" * 3000)
                sys.stderr.flush()
            selected = {"start": {"line": 2, "character": 8}, "end": {"line": 2, "character": 13}}
            location = {"uri": document["uri"], "range": selected}
            if method.endswith("references"):
                result = [location] if message["params"]["context"]["includeDeclaration"] else []
            elif mode == "links":
                result = [{"targetUri": document["uri"], "targetSelectionRange": selected,
                           "targetRange": {"start": {"line": 0, "character": 0}, "end": {"line": 9, "character": 0}}}]
            else: result = location
            send({"jsonrpc": "2.0", "id": message["id"], "result": result})
        elif method == "shutdown":
            Path(pid_path + ".shutdown").write_text("shutdown")
            send({"jsonrpc": "2.0", "id": message["id"], "result": None})
        elif method == "exit":
            Path(pid_path + ".exit").write_text("exit")
            break
except EOFError:
    pass
