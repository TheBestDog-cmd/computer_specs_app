from pathlib import Path

from specforge_desktop import preferences


def test_theme_palettes_exist():
    light = preferences.theme_for("light")
    dark = preferences.theme_for("dark")
    for key in ("app_bg", "panel", "ink", "muted", "accent", "accent_deep", "border"):
        assert key in light
        assert key in dark
    assert light["app_bg"] != dark["app_bg"]


def test_appearance_persists(tmp_path, monkeypatch):
    prefs_file = tmp_path / "preferences.json"
    monkeypatch.setattr(preferences, "preferences_path", lambda: prefs_file)

    assert preferences.get_appearance() == preferences.APPEARANCE_LIGHT
    assert preferences.set_appearance("dark") == preferences.APPEARANCE_DARK
    assert prefs_file.exists()
    assert preferences.get_appearance() == preferences.APPEARANCE_DARK
    assert preferences.set_appearance("nope") == preferences.APPEARANCE_LIGHT
    assert preferences.get_appearance() == preferences.APPEARANCE_LIGHT


def test_load_preferences_handles_corrupt_file(tmp_path, monkeypatch):
    prefs_file = tmp_path / "preferences.json"
    prefs_file.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(preferences, "preferences_path", lambda: prefs_file)
    assert preferences.load_preferences() == {}
    assert preferences.get_appearance() == preferences.APPEARANCE_LIGHT
