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
    assert resources.installed_exe_path().name == "SpecForge.exe"
