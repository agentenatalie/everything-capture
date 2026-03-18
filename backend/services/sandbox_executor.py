"""Sandboxed command execution for AI agent.

All operations are restricted to EXPORTS_DIR and /tmp.
Uses subprocess with argument arrays (no shell=True) to prevent injection.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
from pathlib import Path
from typing import Any

from paths import DATA_ROOT, EXPORTS_DIR

logger = logging.getLogger(__name__)

# Directories the sandbox is allowed to touch
ALLOWED_DIRECTORIES: list[Path] = [DATA_ROOT.resolve(), Path("/tmp").resolve()]

# Working directory for all sandbox operations
SANDBOX_WORKING_DIR = EXPORTS_DIR

# Whitelisted binaries for run_command
COMMAND_WHITELIST: set[str] = {
    "ls", "cat", "head", "tail", "wc", "find", "tree",
    "cp", "mv", "mkdir",
    "zip", "unzip", "tar",
    "git", "curl", "wget",
    "python3", "node",
    "jq", "sort", "grep", "awk", "sed",
    "du", "file", "touch", "echo",
}

# Patterns that are never allowed in any argument
BANNED_PATTERNS: list[str] = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "sudo ",
    "chmod 777",
    "mkfs",
    "dd if=",
    "> /dev/",
    "| sh",
    "| bash",
    "eval ",
]

# Timeout for any single subprocess (seconds)
_SUBPROCESS_TIMEOUT = 60
# Max output capture (bytes)
_MAX_OUTPUT = 65536


class SandboxError(Exception):
    pass


def _validate_path(path_str: str) -> Path:
    """Resolve a path and ensure it's within allowed directories."""
    # Join relative paths to SANDBOX_WORKING_DIR
    if not os.path.isabs(path_str):
        resolved = (SANDBOX_WORKING_DIR / path_str).resolve()
    else:
        resolved = Path(path_str).resolve()

    for allowed in ALLOWED_DIRECTORIES:
        try:
            resolved.relative_to(allowed)
            return resolved
        except ValueError:
            continue

    raise SandboxError(
        f"Path '{path_str}' resolves to '{resolved}' which is outside allowed directories"
    )


def _validate_url(url: str) -> str:
    """Only allow http(s) URLs."""
    if not url or not re.match(r"^https?://", url, re.IGNORECASE):
        raise SandboxError(f"Only http/https URLs are allowed, got: {url!r}")
    return url


def _scan_for_banned(text: str) -> None:
    """Raise if any banned pattern appears in the text."""
    lower = text.lower()
    for pattern in BANNED_PATTERNS:
        if pattern.lower() in lower:
            raise SandboxError(f"Banned pattern detected: {pattern!r}")


async def _run_subprocess(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = _SUBPROCESS_TIMEOUT,
) -> dict[str, Any]:
    """Run a subprocess safely and capture output."""
    # Scrub environment
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "TMPDIR": "/tmp",
    }
    # git needs these
    env["GIT_TERMINAL_PROMPT"] = "0"

    work_dir = cwd or SANDBOX_WORKING_DIR
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Sandbox exec: %s (cwd=%s)", args, work_dir)

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(work_dir),
            env=env,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise SandboxError(f"Command timed out after {timeout}s")
    except FileNotFoundError:
        raise SandboxError(f"Command not found: {args[0]}")

    stdout = (stdout_bytes or b"")[:_MAX_OUTPUT].decode("utf-8", errors="replace")
    stderr = (stderr_bytes or b"")[:_MAX_OUTPUT].decode("utf-8", errors="replace")

    if proc.returncode != 0:
        output = stderr.strip() or stdout.strip()
        raise SandboxError(f"Command failed (exit {proc.returncode}): {output[:500]}")

    return {"stdout": stdout, "stderr": stderr}


async def execute_sandbox_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Dispatch and execute a sandboxed action."""
    SANDBOX_WORKING_DIR.mkdir(parents=True, exist_ok=True)

    if action == "batch":
        return await _action_batch(params)
    elif action == "git_clone":
        return await _action_git_clone(params)
    elif action == "download_file":
        return await _action_download_file(params)
    elif action == "zip_files":
        return await _action_zip_files(params)
    elif action == "list_files":
        return await _action_list_files(params)
    elif action == "read_file":
        return await _action_read_file(params)
    elif action == "write_file":
        return await _action_write_file(params)
    elif action == "move_file":
        return await _action_move_file(params)
    elif action == "delete_file":
        return await _action_delete_file(params)
    elif action == "run_command":
        return await _action_run_command(params)
    else:
        raise SandboxError(f"Unknown action: {action!r}")


# ---------------------------------------------------------------------------
# Individual action handlers
# ---------------------------------------------------------------------------

async def _action_batch(params: dict[str, Any]) -> dict[str, Any]:
    """Execute multiple operations sequentially in one tool call."""
    operations = params.get("operations") or []
    if not isinstance(operations, list) or not operations:
        raise SandboxError("batch requires a non-empty 'operations' array")
    if len(operations) > 20:
        raise SandboxError("batch supports at most 20 operations")

    results: list[dict[str, Any]] = []
    all_files_created: list[str] = []
    last_download_url: str | None = None

    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            results.append({"status": "error", "message": f"Operation {i}: not a dict"})
            continue
        op_action = op.get("action") or ""
        if op_action == "batch":
            results.append({"status": "error", "message": "Nested batch not allowed"})
            continue
        try:
            result = await execute_sandbox_action(op_action, op)
            results.append({"status": "ok", "output": result.get("output", "")[:500]})
            if result.get("files_created"):
                all_files_created.extend(result["files_created"])
            if result.get("download_url"):
                last_download_url = result["download_url"]
        except (SandboxError, Exception) as exc:
            results.append({"status": "error", "message": str(exc)[:300]})

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    fail_count = len(results) - ok_count

    return {
        "status": "ok" if fail_count == 0 else "partial",
        "output": f"Batch: {ok_count} succeeded, {fail_count} failed",
        "results": results,
        "files_created": all_files_created,
        "download_url": last_download_url,
    }


async def _action_git_clone(params: dict[str, Any]) -> dict[str, Any]:
    url = _validate_url(params.get("url") or "")
    output_dir = params.get("output_filename") or ""

    if not output_dir:
        # Derive directory name from URL
        match = re.search(r"/([^/]+?)(?:\.git)?$", url)
        output_dir = match.group(1) if match else "repo"

    target = _validate_path(output_dir)

    args = ["git", "clone", "--depth", "1", url, str(target)]
    result = await _run_subprocess(args)

    return {
        "status": "ok",
        "output": result["stdout"] + result["stderr"],
        "files_created": [str(target)],
        "download_url": None,
    }


async def _action_download_file(params: dict[str, Any]) -> dict[str, Any]:
    url = _validate_url(params.get("url") or "")
    filename = params.get("output_filename") or params.get("path") or ""

    if not filename:
        # Derive filename from URL
        match = re.search(r"/([^/?#]+)$", url)
        filename = match.group(1) if match else "download"

    target = _validate_path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)

    args = ["curl", "-L", "-f", "--max-time", "120", "-o", str(target), url]
    result = await _run_subprocess(args, timeout=120)

    relative = target.relative_to(EXPORTS_DIR) if str(target).startswith(str(EXPORTS_DIR)) else target
    download_url = f"/api/ai/exports/{relative}"

    return {
        "status": "ok",
        "output": f"Downloaded to {target}",
        "files_created": [str(target)],
        "download_url": download_url,
    }


async def _action_zip_files(params: dict[str, Any]) -> dict[str, Any]:
    paths_raw = params.get("paths") or []
    if isinstance(paths_raw, str):
        paths_raw = [paths_raw]

    output_filename = params.get("output_filename") or "archive.zip"
    output_path = _validate_path(output_filename)

    validated_paths: list[str] = []
    for p in paths_raw:
        vp = _validate_path(p)
        if not vp.exists():
            raise SandboxError(f"Path does not exist: {p}")
        validated_paths.append(str(vp))

    if not validated_paths:
        raise SandboxError("No paths provided for zip_files")

    # Use zip -r for directories
    args = ["zip", "-r", str(output_path)] + validated_paths
    result = await _run_subprocess(args, timeout=120)

    relative = output_path.relative_to(EXPORTS_DIR) if str(output_path).startswith(str(EXPORTS_DIR)) else output_path
    download_url = f"/api/ai/exports/{relative}"

    return {
        "status": "ok",
        "output": result["stdout"],
        "files_created": [str(output_path)],
        "download_url": download_url,
    }


async def _action_list_files(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path") or "."
    target = _validate_path(path)

    if not target.exists():
        raise SandboxError(f"Path does not exist: {path}")

    args = ["ls", "-la", str(target)]
    result = await _run_subprocess(args)

    return {"status": "ok", "output": result["stdout"]}


async def _action_read_file(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path") or ""
    if not path:
        raise SandboxError("path is required")

    target = _validate_path(path)
    if not target.is_file():
        raise SandboxError(f"Not a file: {path}")

    content = target.read_text(encoding="utf-8", errors="replace")[:_MAX_OUTPUT]
    return {"status": "ok", "output": content}


async def _action_write_file(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path") or ""
    content = params.get("content") or ""
    if not path:
        raise SandboxError("path is required")

    target = _validate_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    return {
        "status": "ok",
        "output": f"Written {len(content)} chars to {target}",
        "files_created": [str(target)],
    }


async def _action_move_file(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path") or ""
    output_filename = params.get("output_filename") or ""
    if not path or not output_filename:
        raise SandboxError("path and output_filename are required")

    source = _validate_path(path)
    dest = _validate_path(output_filename)

    if not source.exists():
        raise SandboxError(f"Source does not exist: {path}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["mv", str(source), str(dest)]
    await _run_subprocess(args)

    return {"status": "ok", "output": f"Moved {source} -> {dest}"}


async def _action_delete_file(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path") or ""
    if not path:
        raise SandboxError("path is required")

    target = _validate_path(path)
    if not target.exists():
        raise SandboxError(f"Path does not exist: {path}")

    # Only allow deleting files or empty directories — no rm -rf
    if target.is_file():
        target.unlink()
    elif target.is_dir():
        try:
            target.rmdir()  # Only works on empty directories
        except OSError:
            raise SandboxError("Can only delete empty directories. Remove files inside first.")
    else:
        raise SandboxError(f"Cannot delete: {path}")

    return {"status": "ok", "output": f"Deleted {target}"}


async def _action_run_command(params: dict[str, Any]) -> dict[str, Any]:
    command = params.get("command") or ""
    if not command:
        raise SandboxError("command is required")

    _scan_for_banned(command)

    tokens = shlex.split(command)
    if not tokens:
        raise SandboxError("Empty command")

    # Extract the binary name (ignore path prefix)
    binary = os.path.basename(tokens[0])
    if binary not in COMMAND_WHITELIST:
        raise SandboxError(
            f"Command '{binary}' is not in the whitelist. "
            f"Allowed: {', '.join(sorted(COMMAND_WHITELIST))}"
        )

    # Validate that any path-like arguments are within sandbox
    for token in tokens[1:]:
        if token.startswith("-"):
            continue
        # Heuristic: if it looks like a path, validate it
        if "/" in token or token == ".." or token.startswith("~"):
            try:
                _validate_path(token)
            except SandboxError:
                raise SandboxError(f"Argument '{token}' points outside the sandbox")

    result = await _run_subprocess(tokens)
    return {"status": "ok", "output": result["stdout"]}
