"""Packaged asset paths / Windows install helpers for SpecForge."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from specforge_desktop import __version__

# Loose copies left in Desktop/Downloads after the user runs the installer.
_LOOSE_EXE_NAMES = (
    "SpecForge.exe",
    "SpecForge-Setup.exe",
    "SpecForge_Setup.exe",
    "SpecForgeInstaller.exe",
)


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


def _downloads_dir() -> Path | None:
    downloads = Path(os.environ.get("USERPROFILE", "")) / "Downloads"
    return downloads if downloads.is_dir() else None


def _programs_root() -> Path:
    """Per-user Programs folder (no admin elevation required)."""
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "Programs"


def _install_dir() -> Path:
    """Canonical install folder: %LOCALAPPDATA%\\Programs\\SpecForge\\."""
    return _programs_root() / "SpecForge"


def _legacy_appdata_dir() -> Path:
    """Pre-1.3.13 location (%LOCALAPPDATA%\\SpecForge)."""
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "SpecForge"


def installed_exe_path() -> Path:
    """Installed app path — SpecForge.exe under the Programs\\SpecForge folder."""
    return _install_dir() / "SpecForge.exe"


def ensure_appdata_icon() -> Path | None:
    """Install a versioned .ico next to the installed exe (not on the Desktop)."""
    if not getattr(sys, "frozen", False):
        return None
    src = icon_ico()
    if not src.exists():
        return None
    dest_dir = _install_dir()
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


def _copy_exe(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".exe.installing")
    shutil.copy2(src, tmp)
    tmp.replace(dest)


def ensure_app_install() -> Path | None:
    """Install the running exe as %LOCALAPPDATA%\\Programs\\SpecForge\\SpecForge.exe.

    Direct downloads (SpecForge-Setup.exe from GitHub Releases, or a loose
    Desktop/Downloads copy) are treated as an installer: they copy into the
    Programs folder, then the Desktop shortcut points at that install.
    """
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return None

    src = Path(sys.executable).resolve()
    dest = installed_exe_path()
    try:
        if src.resolve() != dest.resolve():
            need_copy = True
            if dest.exists():
                try:
                    need_copy = dest.stat().st_size != src.stat().st_size
                except OSError:
                    need_copy = True
            if need_copy or not dest.exists():
                _copy_exe(src, dest)
        elif not dest.exists():
            # Migrate from the older %LOCALAPPDATA%\\SpecForge layout if present.
            legacy = _legacy_appdata_dir() / "SpecForge.exe"
            if legacy.exists():
                _copy_exe(legacy, dest)

        ensure_appdata_icon()
        notify_shell_of_exe(dest)
        return dest if dest.exists() else None
    except OSError:
        return None


def running_from_app_install() -> bool:
    """True when this frozen process is the canonical Programs\\SpecForge.exe."""
    if not getattr(sys, "frozen", False):
        return False
    try:
        return Path(sys.executable).resolve() == installed_exe_path().resolve()
    except OSError:
        return False


def is_setup_executable(path: Path | None = None) -> bool:
    """True when the exe looks like a downloaded installer (Setup / Installer)."""
    exe = path or (Path(sys.executable) if getattr(sys, "frozen", False) else None)
    if exe is None:
        return False
    name = exe.name.lower()
    return "setup" in name or "install" in name


def relaunch_from_app_install_if_needed() -> bool:
    """If started outside Programs\\SpecForge, install there, start it, and exit.

    This is the installer path for SpecForge-Setup.exe (and other loose copies).
    Returns True when the caller should terminate this process so leftovers can
    be deleted after the file lock is released.
    """
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return False
    if running_from_app_install():
        return False

    dest = ensure_app_install()
    if not dest or not dest.exists():
        return False

    # Point the Desktop shortcut at the Programs install before we exit.
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


def _unlink_with_retry(path: Path, attempts: int = 8, delay: float = 0.35) -> None:
    for _ in range(attempts):
        try:
            if path.exists():
                path.unlink()
            return
        except OSError:
            time.sleep(delay)


def _remove_loose_install_artifacts(installed: Path | None) -> None:
    """Remove Desktop/Downloads installer leftovers after a Programs install."""
    if not installed or not installed.exists():
        return
    installed_resolved = installed.resolve()

    for folder in (_desktop_dir(), _downloads_dir()):
        if not folder:
            continue
        for name in ("SpecForge.ico", *_LOOSE_EXE_NAMES):
            path = folder / name
            try:
                if not path.exists() or not path.is_file():
                    continue
                if path.resolve() == installed_resolved:
                    continue
                _unlink_with_retry(path)
            except OSError:
                pass

    # Drop the pre-1.3.13 AppData\\SpecForge.exe once Programs install exists.
    legacy_exe = _legacy_appdata_dir() / "SpecForge.exe"
    try:
        if legacy_exe.exists() and legacy_exe.resolve() != installed_resolved:
            _unlink_with_retry(legacy_exe)
    except OSError:
        pass


def cleanup_foreign_mei_dirs() -> None:
    """Remove leftover PyInstaller _MEI* dirs except this process's own extract.

    Helps recover from a failed post-update relaunch where the new exe crashed
    with 'Failed to load Python DLL ... python312.dll' because a half-dead
    extract folder was left behind.
    """
    if not getattr(sys, "frozen", False):
        return
    own: Path | None = None
    try:
        own = Path(getattr(sys, "_MEIPASS")).resolve()
    except Exception:
        own = None

    roots = {Path(tempfile.gettempdir())}
    try:
        roots.add(_install_dir() / "tmp")
    except Exception:
        pass
    try:
        roots.add(_legacy_appdata_dir() / "tmp")
    except Exception:
        pass

    for root in roots:
        try:
            if not root.is_dir():
                continue
            for path in root.glob("_MEI*"):
                if not path.is_dir():
                    continue
                try:
                    if own and path.resolve() == own:
                        continue
                except OSError:
                    pass
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def cleanup_stale_update_helpers() -> None:
    """Remove leftover updater scripts from older SpecForge builds."""
    if not getattr(sys, "frozen", False):
        return
    folders = {
        Path(sys.executable).resolve().parent,
        _install_dir(),
        _legacy_appdata_dir(),
    }
    for folder in folders:
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
    """Create/update Desktop\\SpecForge.lnk -> Programs\\SpecForge\\SpecForge.exe."""
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return None

    installed = ensure_app_install()
    _remove_loose_install_artifacts(installed)
    exe = installed or Path(sys.executable).resolve()
    ico = ensure_appdata_icon()
    desktop = _desktop_dir()
    if not desktop:
        return None

    lnk = desktop / "SpecForge.lnk"
    # Prefer the installed .exe as IconLocation (fresh Programs path avoids
    # Desktop shell-cache ghosts). Fall back to the sidecar .ico.
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
