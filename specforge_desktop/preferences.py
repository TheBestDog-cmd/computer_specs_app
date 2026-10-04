"""User preferences for SpecForge (appearance, etc.)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from specforge_desktop import resources

APPEARANCE_LIGHT = "light"
APPEARANCE_DARK = "dark"
_VALID_APPEARANCE = {APPEARANCE_LIGHT, APPEARANCE_DARK}

THEMES: dict[str, dict[str, str]] = {
    APPEARANCE_LIGHT: {
        "app_bg": "#E8F0EC",
        "panel": "#F4F8F6",
        "ink": "#122027",
        "muted": "#4D646E",
        "track": "#D7E3DE",
        "border": "#D5E0DB",
        "accent": "#0F7A6B",
        "accent_deep": "#0B5348",
        "btn_secondary": "#2F5D62",
        "btn_tertiary": "#3D6B74",
        "warn": "#C46B2C",
    },
    APPEARANCE_DARK: {
        "app_bg": "#101618",
        "panel": "#1A2427",
        "ink": "#E7EEF0",
        "muted": "#9BB0B6",
        "track": "#2A373B",
        "border": "#314247",
        "accent": "#2BB39A",
        "accent_deep": "#7DCDC0",
        "btn_secondary": "#1E4A4F",
        "btn_tertiary": "#2A555C",
        "warn": "#E09A5A",
    },
}


def preferences_path() -> Path:
    """Prefer the install folder; fall back to legacy AppData SpecForge."""
    try:
        primary = resources._install_dir() / "preferences.json"  # noqa: SLF001
        primary.parent.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        return resources._legacy_appdata_dir() / "preferences.json"  # noqa: SLF001


def load_preferences() -> dict[str, Any]:
    path = preferences_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_preferences(prefs: dict[str, Any]) -> None:
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prefs, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def get_appearance() -> str:
    mode = str(load_preferences().get("appearance", APPEARANCE_LIGHT)).lower()
    return mode if mode in _VALID_APPEARANCE else APPEARANCE_LIGHT


def set_appearance(mode: str) -> str:
    normalized = str(mode or APPEARANCE_LIGHT).lower()
    if normalized not in _VALID_APPEARANCE:
        normalized = APPEARANCE_LIGHT
    prefs = load_preferences()
    prefs["appearance"] = normalized
    save_preferences(prefs)
    return normalized


def theme_for(mode: str | None = None) -> dict[str, str]:
    key = (mode or get_appearance()).lower()
    if key not in THEMES:
        key = APPEARANCE_LIGHT
    return dict(THEMES[key])
