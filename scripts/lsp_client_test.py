"""Compile and run bounded LSP transport/lifecycle checks without a JDT LS installation."""
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory

project = Path(__file__).resolve().parents[1]
jar = Path(sys.argv[1] if len(sys.argv) > 1 else "target/codeclarity-mcp.jar").resolve()
with TemporaryDirectory(prefix="codeclarity-lsp-client-") as directory:
    subprocess.run(["javac", "--release", "21", "-cp", str(jar), "-d", directory,
                    str(project / "src/test/java/dev/codeclarity/LspClientTest.java")], check=True)
    subprocess.run(["java", "-cp", os.pathsep.join([directory, str(jar)]), "dev.codeclarity.LspClientTest",
                    sys.executable, str(project / "scripts/fake_lsp_server.py"), directory], check=True)
