"""Packaged asset paths for SpecForge (dev checkout and frozen exe)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from specforge_desktop import __version__


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


def _desktop_dir() -> Path | None:
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    if desktop.is_dir():
        return desktop
    public = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
    return public if public.is_dir() else None


def _appdata_icon_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "SpecForge"


def ensure_appdata_icon() -> Path | None:
    """Install a versioned .ico under LocalAppData (not on the Desktop).

    Putting SpecForge.ico next to an exe that lives on the Desktop made a
    visible .ico file appear there. AppData + a .lnk IconLocation avoids that
    and also busts Windows' desktop icon cache across updates.
    """
    if not getattr(sys, "frozen", False):
        return None
    src = icon_ico()
    if not src.exists():
        return None
    dest_dir = _appdata_icon_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"SpecForge-{__version__}.ico"
        if (not dest.exists()) or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        # Stable pointer used by the shortcut.
        stable = dest_dir / "SpecForge.ico"
        shutil.copy2(dest, stable)
        return stable
    except OSError:
        return None


def ensure_sidecar_icon() -> Path | None:
    """Back-compat name: prefer AppData icon; never drop a visible .ico on Desktop."""
    return ensure_appdata_icon()


def _remove_loose_desktop_ico() -> None:
    """Delete leftover SpecForge.ico that older builds copied onto the Desktop."""
    desktop = _desktop_dir()
    if not desktop:
        return
    loose = desktop / "SpecForge.ico"
    try:
        if loose.exists() and loose.is_file():
            loose.unlink()
    except OSError:
        pass
    # Also remove sidecar next to a Desktop-installed exe from older builds.
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if _desktop_dir() and exe.parent.resolve() == _desktop_dir().resolve():
            sibling = exe.with_name("SpecForge.ico")
            try:
                if sibling.exists():
                    sibling.unlink()
            except OSError:
                pass


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
    """Create/update Desktop\\SpecForge.lnk with IconLocation -> LocalAppData .ico.

    Do not leave a raw .ico on the Desktop. Use a .lnk so the brand icon shows
    even when Windows caches the .exe glyph.
    """
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return None

    _remove_loose_desktop_ico()
    exe = Path(sys.executable).resolve()
    ico = ensure_appdata_icon()
    desktop = _desktop_dir()
    if not desktop:
        return None

    lnk = desktop / "SpecForge.lnk"
    ico_path = str(ico) if ico and ico.exists() else str(exe)

    def _q(value: str) -> str:
        return value.replace("'", "''")

    try:
        ps = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{_q(str(lnk))}'); "
            f"$s.TargetPath = '{_q(str(exe))}'; "
            f"$s.WorkingDirectory = '{_q(str(exe.parent))}'; "
            f"$s.IconLocation = '{_q(ico_path)},0'; "
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
