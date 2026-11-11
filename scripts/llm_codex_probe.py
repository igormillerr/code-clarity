"""Run the installed CodeClarity plugin in real Codex CLI; retain raw evidence.

No model/backend is provided by this script. It uses the user's existing Codex
authentication and default model. JAVA_TOOL_OPTIONS supplies a process-local Java
user.home so the unmodified JAR reads an isolated repo-root.txt, not global config.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--mode", choices=("review", "discovery"), default="review")
    parser.add_argument("--temporary-repo-config", action="store_true",
                        help="Temporarily set ~/.codeclarity/repo-root.txt, restore it after the run")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    repo, output = args.repo.resolve(), args.output.resolve()
    if not (repo / ".git").exists():
        parser.error("--repo must be a Git fixture/repository")
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be new or empty (raw evidence is not overwritten)")
    output.mkdir(parents=True, exist_ok=True)
    java_home = output / "java-home"
    (java_home / ".codeclarity").mkdir(parents=True)
    (java_home / ".codeclarity/repo-root.txt").write_text(str(repo), encoding="utf-8")
    cli = shutil.which("codex")
    if not cli:
        parser.error("Codex CLI must be available in PATH")
    prompt = (
        f"This is a CodeClarity integration evaluation. Repository to review: {repo}. "
        "Use only the installed codeclarity plugin and read-only Git for that repository. "
        "Do not edit source, install servers, create feedback or write review history. "
        "Report limitations honestly. Do not read evaluation expected answers. "
    )
    if args.mode == "discovery":
        prompt += (
            "Confirm whether all four installed plugin Skills are discoverable. "
            "Then call the real CodeClarity list_python_changes MCP tool with baseRef main, headRef HEAD. "
            "Do not emulate this call with a shell client. Return the actual SHAs and tool names; "
            "if the plugin tools are unavailable, explain that and stop."
        )
    else:
        prompt += (
            f"Use $readability-review to review committed Java/Python changes main..HEAD. "
            "First call the real plugin list tools for both languages. For this integration probe, "
            "if no CodeClarity MCP tool is exposed, report that blocker and stop immediately. "
            f"Save all independent/frozen/report JSON and Markdown artifacts under {output}. "
            "Use real plugin MCP tools (not shell-emulated calls). Read the changed source at resolved SHAs "
            "before numeric analysis and freeze independent findings before analyze tools. "
            "No changes to input source. Preserve actual Core metric sides and deltas, don't invent absent metrics. "
            "Use INCOMPLETE if required measurements are absent. If history tools are absent, record UNAVAILABLE; "
            "do not substitute direct JSON history writes. Return artifact paths and main verdict."
        )
    (output / "prompt.txt").write_text(prompt, encoding="utf-8")
    command = [cli, "exec", "--ephemeral", "--json", "--sandbox", "workspace-write",
               "-C", str(project), "--add-dir", str(output),
               "-o", str(output / "last-message.md"), prompt]
    environment = dict(os.environ)
    java_option = '-Duser.home="' + java_home.as_posix() + '"'
    environment["JAVA_TOOL_OPTIONS"] = (environment.get("JAVA_TOOL_OPTIONS", "") + " " + java_option).strip()
    result = {"executionLevel": "CODEX_CLI_ATTEMPT", "mode": args.mode, "repo": str(repo),
              "plugin": "codeclarity@codeclarity-local", "status": "FAILED", "note": "Inspect raw events for actual tool calls; exit code alone does not prove E2E."}
    config = Path.home() / ".codeclarity/repo-root.txt"
    previous = None
    config_payload = str(repo).encode("utf-8")
    if args.temporary_repo_config:
        previous = config.read_bytes() if config.exists() else None
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_bytes(config_payload)
        # Some clients filter inherited Java options. Use Main's documented config instead.
        if "JAVA_TOOL_OPTIONS" in os.environ:
            environment["JAVA_TOOL_OPTIONS"] = os.environ["JAVA_TOOL_OPTIONS"]
        else:
            environment.pop("JAVA_TOOL_OPTIONS", None)
    try:
        with (output / "events.jsonl").open("w", encoding="utf-8") as stdout, (output / "stderr.log").open("w", encoding="utf-8") as stderr:
            completed = subprocess.run(command, cwd=project, env=environment, stdout=stdout,
                                       stderr=stderr, timeout=args.timeout, check=False)
        result["exitCode"] = completed.returncode
        result["status"] = "COMPLETED" if completed.returncode == 0 else "FAILED"
    except subprocess.TimeoutExpired:
        result["status"] = "TIMEOUT"
    except OSError as error:
        result["error"] = str(error)
    finally:
        if args.temporary_repo_config:
            if config.exists() and config.read_bytes() == config_payload:
                if previous is None:
                    config.unlink()
                else:
                    config.write_bytes(previous)
                result["temporaryRepoConfigRestored"] = True
            else:
                result["temporaryRepoConfigRestored"] = False
                result["configWarning"] = "Concurrent config change detected; preserved it."
    (output / "attempt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
