from pathlib import Path

from specforge_desktop import resources


def test_icon_assets_exist():
    assert resources.icon_ico().exists()
    assert resources.icon_png().exists()
    assert resources.icon_ico().suffix == ".ico"
    assert resources.icon_png().suffix == ".png"
    assert b"\x89PNG" not in resources.icon_ico().read_bytes()


def test_asset_path_under_assets():
    path = resources.asset_path("specforge.ico")
    assert path.name == "specforge.ico"
    assert path.parent.name == "assets"


def test_small_png_assets_exist():
    assert resources.asset_path("specforge_32.png").exists()
    assert resources.asset_path("specforge_64.png").exists()


def test_install_helpers_noop_when_not_frozen():
    assert resources.ensure_appdata_icon() is None
    assert resources.ensure_sidecar_icon() is None
    assert resources.ensure_app_install() is None
    assert resources.refresh_desktop_shortcut() is None
    assert resources.relaunch_from_app_install_if_needed() is False
    assert resources.running_from_app_install() is False
    assert resources.is_setup_executable() is False
    installed = resources.installed_exe_path()
    assert installed.name == "SpecForge.exe"
    assert installed.parent.name == "SpecForge"
    assert installed.parent.parent.name == "Programs"


def test_is_setup_executable_name():
    assert resources.is_setup_executable(Path("SpecForge-Setup.exe")) is True
    assert resources.is_setup_executable(Path("SpecForge.exe")) is False
