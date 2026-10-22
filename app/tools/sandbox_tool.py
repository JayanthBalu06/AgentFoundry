"""Sandboxed Python execution tool used by the code specialist.

Defense in depth, not a perfect jail:
  1. Static AST check rejects imports of os/sys/subprocess/socket/etc. and
     access to dunder escape hatches (`__import__`, `__subclasses__`, ...)
     before anything runs.
  2. The snippet runs in a *separate subprocess*, started with `-I -S`
     (isolated mode, no site-packages, no inherited env), from a throwaway
     temp directory.
  3. POSIX resource limits cap CPU time, address space, process count, and
     output file size; a wall-clock `timeout` backs up the CPU limit.
This is enough to stop accidents and casual misuse in a portfolio/demo
context; it is not a substitute for a real container/VM sandbox in
production.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

from app.config import get_settings

_BLOCKED_MODULES = {
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "importlib",
    "ctypes", "ssl", "requests", "urllib", "http", "multiprocessing", "signal",
}
_BLOCKED_ATTRS = {"__import__", "__subclasses__", "__globals__", "__builtins__", "__loader__"}


class SandboxViolation(Exception):
    pass


def _static_check(code: str) -> None:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SandboxViolation(f"code does not parse: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BLOCKED_MODULES:
                    raise SandboxViolation(f"import of '{root}' is not allowed in the sandbox")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _BLOCKED_MODULES:
                raise SandboxViolation(f"import of '{root}' is not allowed in the sandbox")
        elif isinstance(node, ast.Attribute) and node.attr in _BLOCKED_ATTRS:
            raise SandboxViolation(f"access to '{node.attr}' is not allowed in the sandbox")
        elif isinstance(node, ast.Name) and node.id in _BLOCKED_ATTRS:
            raise SandboxViolation(f"use of '{node.id}' is not allowed in the sandbox")


def _preexec(max_memory_mb: int, cpu_seconds: int):
    """Apply POSIX resource limits in the child, best-effort per-limit.

    RLIMIT_AS in particular is unreliable on macOS/Darwin: the kernel can
    reject it outright once the process already has more virtual address
    space mapped than the requested limit (true here, since every import
    the parent loaded is already mapped before fork). Linux enforces it
    properly. Either way, a limit we can't set should degrade silently
    rather than take the whole subprocess down with it.
    """

    def _apply() -> None:
        import resource

        mem_bytes = max_memory_mb * 1024 * 1024
        for limit, value in (
            (resource.RLIMIT_AS, (mem_bytes, mem_bytes)),
            (resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds)),
            (resource.RLIMIT_NPROC, (16, 16)),
            (resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024)),
        ):
            try:
                resource.setrlimit(limit, value)
            except (ValueError, OSError):
                pass

    return _apply


def run_python(code: str, timeout: int | None = None, max_memory_mb: int | None = None) -> dict:
    settings = get_settings()
    timeout = timeout or settings.sandbox_timeout_seconds
    max_memory_mb = max_memory_mb or settings.sandbox_max_memory_mb

    _static_check(code)

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "snippet.py"
        script_path.write_text(code)

        preexec_fn = _preexec(max_memory_mb, timeout) if sys.platform != "win32" else None
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-S", str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={},
                preexec_fn=preexec_fn,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "stdout": exc.stdout or "",
                "stderr": "sandbox timeout exceeded",
                "returncode": None,
            }

        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "returncode": proc.returncode,
        }
