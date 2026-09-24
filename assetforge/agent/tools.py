"""The Author's tool surface: search, visit, code_exec and the two controller tools.

These are deliberately small and dependency-free.  `code_exec` runs in a subprocess with a
scratch working directory so the Author can inspect the bundle it was given; the controller
tools are wired by the caller (they need the pipeline's compiler).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

SEARCH_TIMEOUT = float(os.environ.get("ASSETFORGE_SEARCH_TIMEOUT", "30"))
EXEC_TIMEOUT = float(os.environ.get("ASSETFORGE_CODE_EXEC_TIMEOUT", "120"))


def code_exec(args: dict, *, workdir: str | Path | None = None) -> str:
    """Run a short Python snippet or shell command and return its combined output."""
    code = args.get("code") or args.get("command") or ""
    if not code.strip():
        return "code_exec needs a non-empty 'code' argument"
    cwd = str(workdir or os.environ.get("ASSETFORGE_AUTHOR_WORKDIR") or os.getcwd())
    language = (args.get("language") or "python").lower()
    if language in ("shell", "bash", "sh"):
        argv = ["/bin/bash", "-lc", code]
    else:
        argv = [sys.executable, "-c", code]
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                              timeout=EXEC_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"code_exec timed out after {EXEC_TIMEOUT:.0f}s"
    out = (proc.stdout or "") + (proc.stderr or "")
    return out[:40000] or f"(no output; exit code {proc.returncode})"


def visit(args: dict) -> str:
    """Fetch a URL and return its text, truncated."""
    url = args.get("url") or ""
    if not url.startswith(("http://", "https://")):
        return "visit needs an absolute http(s) URL"
    req = urllib.request.Request(url, headers={"User-Agent": "AssetForge/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
            raw = resp.read(200000)
    except Exception as exc:
        return f"visit failed: {type(exc).__name__}: {exc}"
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return "(binary content)"
    return text[:40000]


def search(args: dict) -> str:
    """Query a search endpoint when one is configured, else say so plainly.

    Searching is optional: an Author can complete a task from the bundle alone.  Set
    ASSETFORGE_SEARCH_URL (and optionally ASSETFORGE_SEARCH_KEY) to enable it.
    """
    query = args.get("query") or ""
    endpoint = os.environ.get("ASSETFORGE_SEARCH_URL")
    if not endpoint:
        return ("search is not configured in this environment (set ASSETFORGE_SEARCH_URL to "
                "enable it); rely on the bundle and code_exec instead")
    url = endpoint + ("&" if "?" in endpoint else "?") + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url)
    key = os.environ.get("ASSETFORGE_SEARCH_KEY")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
            return resp.read(60000).decode("utf-8", errors="replace")
    except Exception as exc:
        return f"search failed: {type(exc).__name__}: {exc}"
