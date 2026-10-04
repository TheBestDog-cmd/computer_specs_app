"""Check GitHub for SpecForge updates and pull the latest source."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GITHUB_OWNER = "TheBestDog-cmd"
GITHUB_REPO = "computer_specs_app"
GITHUB_BRANCH = "main"
REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
API_COMMIT = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/commits/{GITHUB_BRANCH}"
API_RELEASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
ZIPBALL_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"
USER_AGENT = "SpecForge-Updater/1.1"


@dataclass
class UpdateInfo:
    local_version: str
    local_commit: str | None
    remote_commit: str | None
    remote_message: str | None
    remote_date: str | None
    release_tag: str | None
    release_url: str | None
    update_available: bool
    mode: str  # git | source | exe
    detail: str


def project_root() -> Path:
    """Return the project / install root for update operations."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _subprocess_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "text": True,
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _http_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, timeout=120, check=False, **_subprocess_kwargs())


def detect_mode(root: Path | None = None) -> str:
    root = root or project_root()
    if getattr(sys, "frozen", False):
        return "exe"
    if (root / ".git").exists() and shutil.which("git"):
        return "git"
    return "source"


def local_commit(root: Path | None = None) -> str | None:
    root = root or project_root()
    if not (root / ".git").exists() or not shutil.which("git"):
        marker = root / ".specforge_commit"
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip()[:40] or None
        return None
    result = _run(["git", "rev-parse", "HEAD"], cwd=root)
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()[:40] or None


def fetch_remote_commit() -> tuple[str | None, str | None, str | None]:
    data = _http_json(API_COMMIT)
    sha = data.get("sha")
    commit = data.get("commit") or {}
    message = (commit.get("message") or "").splitlines()[0] if commit else None
    date = ((commit.get("author") or {}).get("date")) if commit else None
    return (sha[:40] if sha else None, message, date)


def fetch_latest_release() -> tuple[str | None, str | None]:
    try:
        data = _http_json(API_RELEASE)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise
    return data.get("tag_name"), data.get("html_url")


def check_for_updates(local_version: str) -> UpdateInfo:
    root = project_root()
    mode = detect_mode(root)
    local = local_commit(root)
    remote, message, date = fetch_remote_commit()
    release_tag, release_url = fetch_latest_release()

    if remote and local:
        available = remote.lower() != local.lower()
        detail = (
            "A newer commit is on GitHub."
            if available
            else "You are up to date with GitHub main."
        )
    elif remote and not local:
        available = True
        detail = "Could not determine local commit; GitHub main is available to pull/download."
    else:
        available = False
        detail = "Could not read the latest GitHub commit."

    if mode == "exe" and release_tag:
        detail += f" Latest release tag: {release_tag}."

    return UpdateInfo(
        local_version=local_version,
        local_commit=local,
        remote_commit=remote,
        remote_message=message,
        remote_date=date,
        release_tag=release_tag,
        release_url=release_url,
        update_available=available,
        mode=mode,
        detail=detail,
    )


def open_github(page: str = "") -> None:
    url = REPO_URL if not page else f"{REPO_URL}/{page.lstrip('/')}"
    webbrowser.open(url)


def open_releases() -> None:
    webbrowser.open(f"{REPO_URL}/releases")


def pull_with_git(root: Path | None = None) -> str:
    root = root or project_root()
    if not shutil.which("git"):
        raise RuntimeError("git was not found on PATH.")
    if not (root / ".git").exists():
        raise RuntimeError("This folder is not a git checkout. Use Download update instead.")

    fetch = _run(["git", "fetch", "origin", GITHUB_BRANCH], cwd=root)
    if fetch.returncode != 0:
        raise RuntimeError((fetch.stderr or fetch.stdout or "git fetch failed").strip())

    pull = _run(["git", "pull", "--ff-only", "origin", GITHUB_BRANCH], cwd=root)
    if pull.returncode != 0:
        # Fall back to reset --hard only if user is on a clean detached/simple copy? Safer to report.
        raise RuntimeError((pull.stderr or pull.stdout or "git pull failed").strip())

    sha = local_commit(root) or "unknown"
    return f"Pulled latest from origin/{GITHUB_BRANCH} ({sha[:7]})."


def download_source_update(root: Path | None = None) -> str:
    """Download main.zip from GitHub and merge source files into the project root."""
    root = root or project_root()
    if getattr(sys, "frozen", False):
        # Keep source next to the exe so users can rebuild.
        target = root / "computer_specs_app-src"
        target.mkdir(parents=True, exist_ok=True)
    else:
        target = root

    req = urllib.request.Request(ZIPBALL_URL, headers={"User-Agent": USER_AGENT})
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "main.zip"
        with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out:
            shutil.copyfileobj(resp, out)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_path)
        extracted = next(p for p in tmp_path.iterdir() if p.is_dir() and p.name.startswith(GITHUB_REPO))
        # Copy over source files, skip venv/build artifacts
        skip = {".venv", "venv", "node_modules", "dist", "build", ".git", "__pycache__"}
        for src in extracted.rglob("*"):
            rel = src.relative_to(extracted)
            if any(part in skip for part in rel.parts):
                continue
            dest = target / rel
            if src.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

        # Persist remote commit marker when possible
        try:
            remote, _, _ = fetch_remote_commit()
            if remote:
                (target / ".specforge_commit").write_text(remote + "\n", encoding="utf-8")
        except Exception:
            pass

    if getattr(sys, "frozen", False):
        return (
            f"Downloaded latest source to:\\n{target}\\n\\n"
            "Rebuild the exe with scripts\\\\build_executable.bat (CMD) "
            "or scripts\\\\build_executable.ps1 (PowerShell Bypass)."
        )
    return f"Downloaded and applied latest source from GitHub into:\\n{target}"


def apply_update() -> str:
    mode = detect_mode()
    if mode == "git":
        return pull_with_git()
    return download_source_update()
