from specforge_desktop import updater


def test_project_root_exists():
    root = updater.project_root()
    assert root.exists()
    assert (root / "main.py").exists() or (root / "specforge_desktop").exists()


def test_detect_mode_source_or_git():
    mode = updater.detect_mode()
    assert mode in {"git", "source", "exe"}
