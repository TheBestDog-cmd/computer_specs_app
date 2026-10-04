"""Check GitHub for SpecForge updates and apply source or exe updates."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

GITHUB_OWNER = "TheBestDog-cmd"
GITHUB_REPO = "computer_specs_app"
GITHUB_BRANCH = "main"
REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
API_COMMIT = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/commits/{GITHUB_BRANCH}"
API_RELEASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
ZIPBALL_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"
USER_AGENT = "SpecForge-Updater/1.3"
EXE_ASSET_NAME = "SpecForge-Setup.exe"
EXE_ASSET_FALLBACK = "SpecForge.exe"
VERSION_ASSET_NAME = "version.json"
# Release CDN URLs — not api.github.com (avoids unauthenticated 60/hr API quota).
RELEASE_VERSION_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/latest/"
    f"{VERSION_ASSET_NAME}"
)
RELEASE_EXE_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/latest/"
    f"{EXE_ASSET_NAME}"
)
RELEASE_EXE_FALLBACK_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/latest/"
    f"{EXE_ASSET_FALLBACK}"
)
RELEASES_PAGE_URL = f"{REPO_URL}/releases/latest"
# Short in-process cache so opening Updates repeatedly does not re-hit GitHub.
_VERSION_META_CACHE: dict[str, Any] | None = None
_VERSION_META_CACHE_AT = 0.0
_VERSION_META_CACHE_TTL_SEC = 300.0


def parse_version(value: str | None) -> tuple[int, ...]:
    """Parse a dotted version like 1.3.3 into a comparable tuple."""
    if not value:
        return ()
    parts: list[int] = []
    for token in str(value).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer_version(remote: str | None, local: str | None) -> bool:
    """True when remote version is strictly greater than local."""
    r = parse_version(remote)
    l = parse_version(local)
    if not r:
        return False
    if not l:
        return True
    return r > l


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
    exe_asset_url: str | None = None
    remote_version: str | None = None
    can_update_exe: bool = False
    exe_sha256: str | None = None


def project_root() -> Path:
    """Return the project / install root for update operations."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def current_executable() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    # Prefer the canonical AppData install so updates don't rewrite a Desktop
    # copy that Windows still shows with a stale shell icon.
    try:
        from specforge_desktop import resources

        installed = resources.ensure_app_install() or resources.installed_exe_path()
        if installed.exists():
            return installed.resolve()
    except Exception:
        pass
    return Path(sys.executable).resolve()


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


def _friendly_http_error(exc: urllib.error.HTTPError) -> str:
    """Turn GitHub HTTP failures into an actionable SpecForge message."""
    reason = str(exc.reason or "")
    if exc.code == 403 and "rate limit" in reason.lower():
        return (
            "GitHub rate limit exceeded while checking for updates.\n"
            f"Update now (if enabled) still works via direct download.\n"
            f"Or get SpecForge-Setup.exe from {RELEASES_PAGE_URL}."
        )
    if exc.code == 403:
        return (
            f"GitHub returned HTTP 403 ({reason}).\n"
            f"Try again later, or download from {RELEASES_PAGE_URL}."
        )
    return f"HTTP Error {exc.code}: {reason}"


def _http_get_bytes(url: str, timeout: int = 20) -> bytes:
    """GET bytes with browser-like headers (no API Accept).

    GitHub release asset URLs (/releases/download/...) 403 with
    'rate limit exceeded' when Accept looks like an API request
    (e.g. application/json). Mirror the working download path.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_json(url: str) -> dict[str, Any]:
    if "api.github.com" in url:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                raise RuntimeError(_friendly_http_error(exc)) from exc
            raise
    try:
        raw = _http_get_bytes(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise RuntimeError(_friendly_http_error(exc)) from exc
        raise
    return json.loads(raw.decode("utf-8"))


def _http_download(
    url: str,
    dest: Path,
    progress: Callable[[int, int | None], None] | None = None,
) -> None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as out:
        total = resp.headers.get("Content-Length")
        total_i = int(total) if total and total.isdigit() else None
        read = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            read += len(chunk)
            if progress:
                progress(read, total_i)


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        timeout=120,
        check=False,
        **_subprocess_kwargs(),
    )


def detect_mode(root: Path | None = None) -> str:
    root = root or project_root()
    if getattr(sys, "frozen", False):
        return "exe"
    if (root / ".git").exists() and shutil.which("git"):
        return "git"
    return "source"


def local_commit(root: Path | None = None) -> str | None:
    root = root or project_root()
    marker = root / ".specforge_commit"
    if marker.exists():
        value = marker.read_text(encoding="utf-8").strip()[:40]
        if value:
            return value
    if not (root / ".git").exists() or not shutil.which("git"):
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


def fetch_latest_release() -> dict[str, Any] | None:
    try:
        return _http_json(API_RELEASE)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def fetch_published_version_meta(*, bypass_cache: bool = False) -> dict[str, Any] | None:
    """Load version.json from the GitHub release CDN (not the REST API).

    Uses the same Accept headers as the working exe download path. Sending
    Accept: application/json to /releases/download/ can 403 with
    'rate limit exceeded' even though the file download itself succeeds.
    """
    global _VERSION_META_CACHE, _VERSION_META_CACHE_AT

    now = time.monotonic()
    if (
        not bypass_cache
        and _VERSION_META_CACHE is not None
        and (now - _VERSION_META_CACHE_AT) < _VERSION_META_CACHE_TTL_SEC
    ):
        return dict(_VERSION_META_CACHE)

    try:
        meta = _http_json(RELEASE_VERSION_URL)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not isinstance(meta, dict):
        return None

    _VERSION_META_CACHE = dict(meta)
    _VERSION_META_CACHE_AT = now
    return dict(meta)


def _asset_map(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = release.get("assets") or []
    return {a.get("name"): a for a in assets if a.get("name")}


def check_for_updates(local_version: str) -> UpdateInfo:
    root = project_root()
    mode = detect_mode(root)
    local = local_commit(root)

    remote: str | None = None
    message: str | None = None
    date: str | None = None
    release_tag: str | None = None
    release_url: str | None = RELEASES_PAGE_URL
    exe_url: str | None = None
    remote_version: str | None = None
    can_update_exe = False
    exe_sha256: str | None = None

    # Prefer CDN version.json so frozen installs never burn GitHub API quota.
    meta: dict[str, Any] | None = None
    try:
        meta = fetch_published_version_meta()
    except (urllib.error.HTTPError, RuntimeError):
        if mode == "exe":
            raise
        meta = None
    except Exception:
        meta = None

    if meta:
        remote_version = str(meta.get("version") or "") or None
        if meta.get("commit"):
            remote = str(meta["commit"])[:40]
        if meta.get("sha256"):
            exe_sha256 = str(meta["sha256"]).strip().lower()
        release_tag = str(meta.get("tag") or "latest")
        can_update_exe = True
        exe_url = RELEASE_EXE_URL

    # Source/git installs may still need the REST API for commit comparison.
    # Frozen exe installs skip it entirely once version.json is available.
    if mode != "exe" and not (remote_version and remote):
        try:
            remote, message, date = fetch_remote_commit()
        except (urllib.error.HTTPError, RuntimeError):
            if not meta:
                raise
        if not meta:
            try:
                release = fetch_latest_release()
            except (urllib.error.HTTPError, RuntimeError):
                release = None
            if release:
                release_tag = release.get("tag_name") or release_tag
                release_url = release.get("html_url") or release_url
                assets = _asset_map(release)
                exe_asset = assets.get(EXE_ASSET_NAME) or assets.get(EXE_ASSET_FALLBACK)
                if exe_asset and exe_asset.get("browser_download_url"):
                    exe_url = exe_asset["browser_download_url"]
                    can_update_exe = True
                    digest = str(exe_asset.get("digest") or "")
                    if digest.lower().startswith("sha256:"):
                        exe_sha256 = digest.split(":", 1)[1].strip().lower()
                version_asset = assets.get(VERSION_ASSET_NAME)
                if version_asset and version_asset.get("browser_download_url"):
                    try:
                        api_meta = _http_json(version_asset["browser_download_url"])
                        remote_version = api_meta.get("version") or remote_version
                        if api_meta.get("commit"):
                            remote = str(api_meta["commit"])[:40]
                        if api_meta.get("sha256"):
                            exe_sha256 = str(api_meta["sha256"]).strip().lower()
                    except Exception:
                        pass

    if remote_version:
        available = is_newer_version(remote_version, local_version)
        detail = (
            f"A newer version is available ({remote_version} > {local_version})."
            if available
            else f"You are up to date (installed {local_version}; GitHub {remote_version})."
        )
    elif remote and local:
        available = remote.lower() != local.lower()
        detail = (
            "A newer build is on GitHub."
            if available
            else "You are up to date with GitHub."
        )
    elif remote and not local:
        available = is_newer_version(remote_version, local_version) if remote_version else False
        detail = (
            f"GitHub publishes version {remote_version}; this install has no local commit marker."
            if available
            else "Local build marker missing; cannot confirm a newer version is available."
        )
    else:
        available = False
        detail = "Could not read the latest GitHub release metadata."

    if mode == "exe":
        # Frozen installs only update when a newer version.json + SpecForge.exe exist.
        if remote_version:
            available = is_newer_version(remote_version, local_version)
        else:
            available = False
            detail = (
                "No version.json in the latest GitHub Release yet, so SpecForge cannot confirm "
                "a newer version. Wait for CI to publish, then Check again."
            )
        if available and can_update_exe:
            detail += " Update now will download SpecForge-Setup.exe and replace this app on restart."
        elif available and not can_update_exe:
            available = False
            detail = (
                f"Version {remote_version} is listed, but SpecForge-Setup.exe is not in the latest "
                "release assets yet (CI may still be publishing)."
            )
        elif can_update_exe and not available:
            detail += " Update now stays disabled until a newer version is published."
    elif release_tag:
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
        exe_asset_url=exe_url,
        remote_version=remote_version,
        can_update_exe=can_update_exe and available,
        exe_sha256=exe_sha256,
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
        raise RuntimeError((pull.stderr or pull.stdout or "git pull failed").strip())

    sha = local_commit(root) or "unknown"
    return f"Pulled latest from origin/{GITHUB_BRANCH} ({sha[:7]})."


def download_source_update(root: Path | None = None) -> str:
    """Download main.zip from GitHub and merge source files into the project root."""
    root = root or project_root()
    if getattr(sys, "frozen", False):
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
        extracted = next(
            p for p in tmp_path.iterdir() if p.is_dir() and p.name.startswith(GITHUB_REPO)
        )
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

        try:
            remote, _, _ = fetch_remote_commit()
            if remote:
                (target / ".specforge_commit").write_text(remote + "\n", encoding="utf-8")
        except Exception:
            pass

    if getattr(sys, "frozen", False):
        return (
            f"Downloaded latest source to:\n{target}\n\n"
            "No exe asset was available, so rebuild SpecForge.exe with "
            "scripts\\build_executable.bat after opening that folder."
        )
    return f"Downloaded and applied latest source from GitHub into:\n{target}"



def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def verify_downloaded_exe(path: Path, expected_sha256: str | None = None) -> None:
    """Reject corrupt/HTML downloads before we try to relaunch SpecForge."""
    if not path.exists():
        raise RuntimeError("Downloaded SpecForge.exe is missing.")
    size = path.stat().st_size
    if size < 8_000_000:
        raise RuntimeError(
            f"Downloaded SpecForge.exe is only {size} bytes — aborting update "
            "(likely an incomplete download or HTML error page)."
        )
    with open(path, "rb") as handle:
        magic = handle.read(2)
    if magic != b"MZ":
        raise RuntimeError(
            "Downloaded file is not a Windows executable (missing MZ header). "
            "Aborting update."
        )
    if expected_sha256:
        got = _sha256_file(path)
        if got != expected_sha256.lower():
            raise RuntimeError(
                "Downloaded SpecForge.exe failed checksum verification.\n"
                f"Expected sha256 {expected_sha256}\nGot {got}\n"
                "Delete SpecForge.exe.new and try Update now again."
            )


def _windows_update_ps1(
    exe_path: Path,
    new_path: Path,
    commit: str | None,
    pid: int,
) -> Path:
    """Write a hidden PowerShell swap script (no visible CMD windows).

    Waits for *this* SpecForge PID to exit, clears leftover PyInstaller _MEI
    extract dirs (the usual python312.dll failure), copies the new exe, then
    relaunches — all with -WindowStyle Hidden.
    """
    script = exe_path.parent / "_specforge_update.ps1"
    log = exe_path.parent / "_specforge_update.log"
    marker = exe_path.parent / ".specforge_commit"
    commit_lit = commit.replace("'", "''") if commit else ""
    # PowerShell single-quoted paths; double any embedded single quotes.
    exe_lit = str(exe_path).replace("'", "''")
    new_lit = str(new_path).replace("'", "''")
    log_lit = str(log).replace("'", "''")
    dir_lit = str(exe_path.parent).replace("'", "''")
    marker_lit = str(marker).replace("'", "''")

    commit_block = (
        f"Set-Content -LiteralPath '{marker_lit}' -Value '{commit_lit}' -Encoding ASCII\n"
        if commit
        else "# no commit marker\n"
    )

    stale_cmd_pat = r"^(cmd|wscript|cscript)\.exe$"
    stale_line_pat = r"_specforge_update\.bat|SpecForge\.exe\.new"
    extract_dir = str((exe_path.parent / "tmp").resolve()).replace("'", "''")

    ps = f"""$ErrorActionPreference = 'Continue'
$exe = '{exe_lit}'
$new = '{new_lit}'
$log = '{log_lit}'
$dir = '{dir_lit}'
$extractRoot = '{extract_dir}'
$pidToWait = {int(pid)}
function Log([string]$msg) {{
  $line = "{{0}} {{1}}" -f (Get-Date -Format o), $msg
  Add-Content -LiteralPath $log -Value $line -Encoding UTF8
}}
Set-Content -LiteralPath $log -Value '' -Encoding UTF8
Log "SpecForge silent update starting (wait PID $pidToWait)"

# Wait briefly for the installing process to exit, then FORCE-kill any leftover
# SpecForge.exe. Never spin forever (old bat helpers hung with a blank console).
try {{
  $proc = Get-Process -Id $pidToWait -ErrorAction SilentlyContinue
  if ($proc) {{
    Log "Waiting up to 25s for PID $pidToWait"
    Wait-Process -Id $pidToWait -Timeout 25 -ErrorAction SilentlyContinue
  }}
}} catch {{
  Log "Wait-Process: $_"
}}

$alive = @(Get-Process -Name 'SpecForge' -ErrorAction SilentlyContinue)
if ($alive.Count -gt 0) {{
  Log ("Force-stopping remaining SpecForge processes: " + (($alive | ForEach-Object {{ $_.Id }}) -join ','))
  Stop-Process -Name 'SpecForge' -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 3
}}

# Kill leftover visible updaters from older SpecForge builds (blank cmd windows).
# Do NOT match this PowerShell process (its command line also contains _specforge_update).
$myPid = $PID
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object {{
    $_.ProcessId -ne $myPid -and
    $_.Name -match '{stale_cmd_pat}' -and
    $_.CommandLine -and
    ($_.CommandLine -match '{stale_line_pat}')
  }} |
  ForEach-Object {{
    try {{
      Log ("Stopping stale updater PID $($_.ProcessId): $($_.Name)")
      Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
    }} catch {{}}
  }}

Log "Process clear; settling and cleaning _MEI extract dirs"
Start-Sleep -Seconds 4

function Clear-MeiDirs([string]$root) {{
  if (-not (Test-Path -LiteralPath $root)) {{ return }}
  Get-ChildItem -LiteralPath $root -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue |
    ForEach-Object {{
      try {{
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
        Log ("Removed " + $_.FullName)
      }} catch {{
        Log ("Could not remove " + $_.FullName + ": $_")
      }}
    }}
}}

# Stale PyInstaller one-file unpack dirs cause: Failed to load Python DLL ... python312.dll
Clear-MeiDirs $env:TEMP
Clear-MeiDirs $env:TMP
Clear-MeiDirs $extractRoot
try {{
  New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
}} catch {{
  Log "Could not create private extract dir: $_"
}}

Start-Sleep -Seconds 2

if (-not (Test-Path -LiteralPath $new)) {{
  Log "Missing downloaded file: $new"
  exit 1
}}
$expectedSize = (Get-Item -LiteralPath $new).Length

for ($i = 0; $i -lt 80; $i++) {{
  try {{
    if (Test-Path -LiteralPath $exe) {{
      Remove-Item -LiteralPath $exe -Force -ErrorAction Stop
    }}
    if (-not (Test-Path -LiteralPath $exe)) {{ break }}
  }} catch {{
    Start-Sleep -Milliseconds 400
  }}
}}

try {{
  # Same-volume rename avoids a half-written SpecForge.exe if copy is interrupted.
  Move-Item -LiteralPath $new -Destination $exe -Force
  Log "Moved new exe into place"
}} catch {{
  try {{
    Copy-Item -LiteralPath $new -Destination $exe -Force
    Remove-Item -LiteralPath $new -Force -ErrorAction SilentlyContinue
    Log "Copied new exe into place (move fallback)"
  }} catch {{
    Log "Copy/move failed: $_"
    exit 1
  }}
}}

if (-not (Test-Path -LiteralPath $exe)) {{
  Log "Installed exe missing after replace"
  exit 1
}}
$gotSize = (Get-Item -LiteralPath $exe).Length
if ($gotSize -ne $expectedSize) {{
  Log "Size mismatch after replace: expected $expectedSize got $gotSize"
  exit 1
}}

{commit_block}
try {{ Unblock-File -LiteralPath $exe -ErrorAction SilentlyContinue }} catch {{}}
try {{
  Remove-Item -LiteralPath ($exe + ':Zone.Identifier') -Force -ErrorAction SilentlyContinue
}} catch {{}}

# Nudge Explorer / Defender to finish touching the new file before we launch.
try {{ (Get-Item -LiteralPath $exe).LastWriteTime = Get-Date }} catch {{}}
Start-Sleep -Seconds 4

Log "Launching $exe (private TEMP=$extractRoot)"
$env:SPEC_FORGE_UPDATED = '1'
$env:TEMP = $extractRoot
$env:TMP = $extractRoot

$launched = $false
for ($t = 0; $t -lt 5; $t++) {{
  Clear-MeiDirs $extractRoot
  try {{
    $p = Start-Process -FilePath $exe -WorkingDirectory $dir -PassThru
    Log ("Start-Process attempt $($t+1) PID=$($p.Id)")
    Start-Sleep -Seconds 4
    $p.Refresh()
    if (-not $p.HasExited) {{
      Log "Launch appears healthy"
      $launched = $true
      break
    }}
    Log ("Process exited early code=$($p.ExitCode); retrying after MEI cleanup")
  }} catch {{
    Log "Launch failed: $_"
  }}
  Start-Sleep -Seconds 2
}}

if (-not $launched) {{
  Log "WARNING: could not confirm a healthy SpecForge relaunch"
}}

# Self-delete when possible
Start-Sleep -Seconds 1
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
exit 0
"""
    script.write_text(ps, encoding="utf-8")
    return script


def _windows_replace_script(
    exe_path: Path,
    new_path: Path,
    commit: str | None,
    pid: int | None = None,
) -> Path:
    """Back-compat name used by tests; writes the silent PowerShell updater."""
    return _windows_update_ps1(exe_path, new_path, commit, pid or os.getpid())


def _launch_silent_updater(script: Path, cwd: Path) -> None:
    """Run the update script with no visible console windows."""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        raise RuntimeError("powershell was not found on PATH; cannot apply exe update silently.")

    # VBScript Run(..., 0, False) never shows a console — more reliable than
    # launching powershell.exe directly (which briefly flashes on some PCs).
    vbs = cwd / "_specforge_update.vbs"
    cmd = (
        f'"{powershell}" -NoProfile -NonInteractive -ExecutionPolicy Bypass '
        f'-WindowStyle Hidden -File "{script}"'
    )
    vbs_cmd = cmd.replace('"', '""')
    vbs.write_text(
        "\r\n".join(
            [
                'Set sh = CreateObject("WScript.Shell")',
                f'sh.Run "{vbs_cmd}", 0, False',
                "",
            ]
        ),
        encoding="utf-8",
    )

    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    detached = 0x00000008
    new_group = 0x00000200
    flags = create_no_window | detached | new_group

    wscript = shutil.which("wscript") or shutil.which("wscript.exe") or "wscript.exe"
    subprocess.Popen(
        [wscript, "//B", "//Nologo", str(vbs)],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def download_and_replace_exe(
    asset_url: str | None = None,
    remote_commit: str | None = None,
    progress: Callable[[int, int | None], None] | None = None,
    expected_sha256: str | None = None,
) -> str:
    """Download SpecForge.exe from GitHub Releases and schedule a replace+restart."""
    if platform.system() != "Windows":
        raise RuntimeError("Automatic exe replacement is currently supported on Windows.")
    exe = current_executable()
    if exe is None:
        raise RuntimeError("Not running as a frozen SpecForge.exe.")

    if not asset_url:
        from specforge_desktop import __version__ as installed_version

        info = check_for_updates(installed_version)
        if not info.update_available:
            raise RuntimeError(
                info.detail
                or "Already up to date — no newer SpecForge version is available."
            )
        asset_url = info.exe_asset_url
        remote_commit = remote_commit or info.remote_commit
        expected_sha256 = expected_sha256 or info.exe_sha256
        if not asset_url:
            raise RuntimeError(
                "No SpecForge-Setup.exe found in the latest GitHub Release yet. "
                "Wait for the Release workflow on main to finish, then try again."
            )

    expected_sha = expected_sha256
    if expected_sha is None or remote_commit is None:
        try:
            from specforge_desktop import __version__ as installed_version

            probed = check_for_updates(installed_version)
            expected_sha = expected_sha or probed.exe_sha256
            remote_commit = remote_commit or probed.remote_commit
        except Exception:
            pass

    new_path = exe.with_suffix(exe.suffix + ".new")
    if new_path.exists():
        new_path.unlink()
    _http_download(asset_url, new_path, progress=progress)
    # Ensure bytes are on disk before the swap script runs.
    with open(new_path, "rb+") as handle:
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass

    verify_downloaded_exe(new_path, expected_sha256=expected_sha)

    # Best-effort clear of leftover extracts before we exit and the swap script runs.
    try:
        from specforge_desktop import resources as _resources

        _resources.cleanup_foreign_mei_dirs()
    except Exception:
        pass

    script = _windows_update_ps1(exe, new_path, remote_commit, os.getpid())
    _launch_silent_updater(script, exe.parent)
    return (
        "Downloaded the latest SpecForge build from GitHub Releases.\n"
        "SpecForge will close and restart quietly with the new build "
        "(no terminal windows).\n"
        "If launch fails, see _specforge_update.log next to SpecForge.exe, "
        "delete %TEMP%\\_MEI* folders, and try again."
    )



def apply_update(
    local_version: str | None = None,
    progress: Callable[[int, int | None], None] | None = None,
) -> tuple[str, bool]:
    """Apply update only when a newer version/build is available.

    Returns (message, should_restart_app).
    """
    from specforge_desktop import __version__ as installed_version

    version = local_version or installed_version
    info = check_for_updates(version)
    if not info.update_available:
        raise RuntimeError(
            info.detail
            or "Already up to date — Update now is only allowed when a newer version is available."
        )

    mode = info.mode
    if mode == "exe":
        if info.can_update_exe and info.exe_asset_url:
            msg = download_and_replace_exe(
                info.exe_asset_url,
                info.remote_commit,
                progress=progress,
                expected_sha256=info.exe_sha256,
            )
            return msg, True
        raise RuntimeError(
            "A newer version is listed, but SpecForge-Setup.exe is not downloadable yet. "
            "Wait for the GitHub Release workflow, then try again."
        )
    if mode == "git":
        return pull_with_git(), False
    return download_source_update(), False
