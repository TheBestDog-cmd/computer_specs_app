from pathlib import Path

from specforge_desktop import resources


def test_icon_assets_exist():
    assert resources.icon_ico().exists()
    assert resources.icon_png().exists()
    assert resources.icon_ico().suffix == ".ico"
    assert resources.icon_png().suffix == ".png"


def test_asset_path_under_assets():
    path = resources.asset_path("specforge.ico")
    assert path.name == "specforge.ico"
    assert path.parent.name == "assets"
