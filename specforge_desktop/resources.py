"""Packaged asset paths / Windows install helpers for SpecForge."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
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


def _appdata_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "SpecForge"


def installed_exe_path() -> Path:
    """Canonical install location — avoids Desktop path icon-cache ghosts."""
    return _appdata_dir() / "SpecForge.exe"


def ensure_appdata_icon() -> Path | None:
    """Install a versioned .ico under LocalAppData (not on the Desktop)."""
    if not getattr(sys, "frozen", False):
        return None
    src = icon_ico()
    if not src.exists():
        return None
    dest_dir = _appdata_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"SpecForge-{__version__}.ico"
        if (not dest.exists()) or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        stable = dest_dir / "SpecForge.ico"
        shutil.copy2(dest, stable)
        return stable
    except OSError:
        return None


def ensure_sidecar_icon() -> Path | None:
    """Back-compat name."""
    return ensure_appdata_icon()


def notify_shell_of_exe(path: Path) -> None:
    """Ask Explorer to drop cached icons for this file path."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        SHCNE_UPDATEITEM = 0x00002000
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_PATHW = 0x0005
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_UPDATEITEM, SHCNF_PATHW, str(path), None
        )
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
        )
    except Exception:
        pass


def ensure_app_install() -> Path | None:
    """Copy the running exe into %LOCALAPPDATA%\\SpecForge\\SpecForge.exe.

    Desktop/Downloads copies keep a sticky wrong icon in the shell cache after
    in-place updates. A stable AppData path + Desktop .lnk shows the brand
    icon on the shortcut and on the real exe in Explorer.
    """
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return None

    src = Path(sys.executable).resolve()
    dest = installed_exe_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            need_copy = True
            if dest.exists():
                try:
                    need_copy = dest.stat().st_size != src.stat().st_size
                except OSError:
                    need_copy = True
            if need_copy or not dest.exists():
                # Running onefile can still be read/copied on Windows.
                tmp = dest.with_suffix(".exe.installing")
                shutil.copy2(src, tmp)
                tmp.replace(dest)

        ensure_appdata_icon()
        notify_shell_of_exe(dest)
        return dest if dest.exists() else None
    except OSError:
        return None


def running_from_app_install() -> bool:
    """True when this frozen process is the canonical AppData SpecForge.exe."""
    if not getattr(sys, "frozen", False):
        return False
    try:
        return Path(sys.executable).resolve() == installed_exe_path().resolve()
    except OSError:
        return False


def relaunch_from_app_install_if_needed() -> bool:
    """If started outside AppData, install there, start that copy, and exit.

    Returns True when the caller should terminate this process. That lets the
    new AppData instance delete a locked Desktop SpecForge.exe leftover.
    """
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return False
    if running_from_app_install():
        return False

    dest = ensure_app_install()
    if not dest or not dest.exists():
        return False

    # Point the Desktop shortcut at AppData before we exit the Desktop copy.
    try:
        refresh_desktop_shortcut()
    except Exception:
        pass

    try:
        flags = 0
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.Popen(
            [str(dest)],
            cwd=str(dest.parent),
            close_fds=True,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def _remove_loose_desktop_artifacts(installed: Path | None) -> None:
    """Remove Desktop SpecForge.ico / leftover Desktop SpecForge.exe after migrate."""
    desktop = _desktop_dir()
    if not desktop:
        return
    for name in ("SpecForge.ico",):
        path = desktop / name
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except OSError:
            pass

    # If we successfully installed to AppData, remove the Desktop .exe copy so
    # the user isn't looking at a cache-stale file next to the good shortcut.
    if installed and installed.exists():
        desktop_exe = desktop / "SpecForge.exe"
        try:
            if (
                desktop_exe.exists()
                and desktop_exe.resolve() != installed.resolve()
            ):
                # Parent Desktop process may have just exited — retry briefly.
                for _ in range(8):
                    try:
                        desktop_exe.unlink()
                        break
                    except OSError:
                        time.sleep(0.35)
        except OSError:
            pass


def cleanup_stale_update_helpers() -> None:
    """Remove leftover updater scripts from older SpecForge builds."""
    if not getattr(sys, "frozen", False):
        return
    for folder in {Path(sys.executable).resolve().parent, _appdata_dir()}:
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
    """Create/update Desktop\\SpecForge.lnk -> AppData exe + AppData .ico."""
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return None

    installed = ensure_app_install()
    _remove_loose_desktop_artifacts(installed)
    exe = installed or Path(sys.executable).resolve()
    ico = ensure_appdata_icon()
    desktop = _desktop_dir()
    if not desktop:
        return None

    lnk = desktop / "SpecForge.lnk"
    # Prefer the .exe itself as IconLocation now that it lives on a fresh AppData
    # path (shell cache no longer stuck on an old Desktop path). Fall back to .ico.
    icon_loc = f"{exe},0" if exe.exists() else (f"{ico},0" if ico else "")

    def _q(value: str) -> str:
        return value.replace("'", "''")

    try:
        ps = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{_q(str(lnk))}'); "
            f"$s.TargetPath = '{_q(str(exe))}'; "
            f"$s.WorkingDirectory = '{_q(str(exe.parent))}'; "
            f"$s.IconLocation = '{_q(icon_loc)}'; "
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
            timeout=20,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        notify_shell_of_exe(exe)
        return lnk if lnk.exists() else None
    except Exception:
        return None
