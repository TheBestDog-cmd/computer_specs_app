"""Packaged asset paths for SpecForge (dev checkout and frozen exe)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller onefile extract dir
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def asset_path(*parts: str) -> Path:
    return project_root().joinpath("assets", *parts)


def icon_ico() -> Path:
    return asset_path("specforge.ico")


def icon_png() -> Path:
    # Prefer a small PNG for Tk PhotoImage (title-bar); fall back to 256 master.
    for name in ("specforge_32.png", "specforge_64.png", "specforge.png"):
        path = asset_path(name)
        if path.exists():
            return path
    return asset_path("specforge.png")


def ensure_sidecar_icon() -> Path | None:
    """Copy SpecForge.ico next to the frozen exe so desktop shortcuts can pin it."""
    if not getattr(sys, "frozen", False):
        return None
    src = icon_ico()
    if not src.exists():
        return None
    dest = Path(sys.executable).resolve().with_name("SpecForge.ico")
    try:
        if (not dest.exists()) or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        return dest
    except OSError:
        return None


def cleanup_stale_update_helpers() -> None:
    """Remove leftover updater scripts from older SpecForge builds (bat/find hangs)."""
    if not getattr(sys, "frozen", False):
        return
    folder = Path(sys.executable).resolve().parent
    for name in (
        "_specforge_update.bat",
        "_specforge_update.cmd",
        "_specforge_update.ps1",
        "_specforge_update.vbs",
    ):
        path = folder / name
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def refresh_desktop_shortcut() -> Path | None:
    """Create/update a Desktop SpecForge.lnk that uses SpecForge.ico explicitly.

    Windows caches .exe icons aggressively after in-place updates; pointing the
    shortcut at the sidecar .ico makes the brand icon show up reliably.
    """
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return None
    exe = Path(sys.executable).resolve()
    ico = ensure_sidecar_icon() or exe.with_name("SpecForge.ico")
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    if not desktop.is_dir():
        desktop = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
    if not desktop.is_dir():
        return None
    lnk = desktop / "SpecForge.lnk"
    # PowerShell COM shortcut write — hidden, no window.
    try:
        import subprocess

        ico_path = str(ico if ico.exists() else exe)
        ps = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{str(lnk).replace(chr(39), chr(39)+chr(39))}'); "
            f"$s.TargetPath = '{str(exe).replace(chr(39), chr(39)+chr(39))}'; "
            f"$s.WorkingDirectory = '{str(exe.parent).replace(chr(39), chr(39)+chr(39))}'; "
            f"$s.IconLocation = '{ico_path.replace(chr(39), chr(39)+chr(39))},0'; "
            f"$s.Description = 'SpecForge — Real-time Computer Specs'; "
            f"$s.Save()"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            check=False,
            timeout=15,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return lnk if lnk.exists() else None
    except Exception:
        return None
