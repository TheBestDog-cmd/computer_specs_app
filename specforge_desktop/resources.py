"""Packaged asset paths for SpecForge (dev checkout and frozen exe)."""

from __future__ import annotations

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
    return asset_path("specforge.png")


def ensure_sidecar_icon() -> Path | None:
    """Copy SpecForge.ico next to the frozen exe so desktop shortcuts can see it."""
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
