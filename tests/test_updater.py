from specforge_desktop import updater


def test_project_root_exists():
    root = updater.project_root()
    assert root.exists()
    assert (root / "main.py").exists() or (root / "specforge_desktop").exists()


def test_detect_mode_source_or_git():
    mode = updater.detect_mode()
    assert mode in {"git", "source", "exe"}


def test_apply_update_signature():
    # apply_update returns (message, should_restart)
    assert callable(updater.apply_update)
    assert callable(updater.download_and_replace_exe)


def test_parse_version():
    assert updater.parse_version("1.3.4") == (1, 3, 4)
    assert updater.parse_version("v2.0") == (2, 0)
    assert updater.parse_version("") == ()
    assert updater.parse_version(None) == ()


def test_is_newer_version():
    assert updater.is_newer_version("1.3.4", "1.3.3") is True
    assert updater.is_newer_version("1.3.3", "1.3.3") is False
    assert updater.is_newer_version("1.3.2", "1.3.3") is False
    assert updater.is_newer_version(None, "1.3.3") is False
    assert updater.is_newer_version("1.4.0", "1.3.9") is True


def test_check_for_updates_uses_version_when_present(monkeypatch):
    monkeypatch.setattr(updater, "detect_mode", lambda root=None: "source")
    monkeypatch.setattr(updater, "local_commit", lambda root=None: "aaa")
    monkeypatch.setattr(updater, "fetch_remote_commit", lambda: ("bbb", "msg", "2026-01-01"))
    monkeypatch.setattr(
        updater,
        "fetch_latest_release",
        lambda: {
            "tag_name": "latest",
            "html_url": "https://example.com",
            "assets": [
                {"name": "version.json", "browser_download_url": "https://example.com/version.json"},
                {"name": "SpecForge.exe", "browser_download_url": "https://example.com/SpecForge.exe"},
            ],
        },
    )

    def fake_json(url: str):
        if url.endswith("version.json"):
            return {"version": "1.3.4", "commit": "bbb"}
        raise AssertionError(url)

    monkeypatch.setattr(updater, "_http_json", fake_json)

    newer = updater.check_for_updates("1.3.3")
    assert newer.update_available is True
    assert newer.remote_version == "1.3.4"

    current = updater.check_for_updates("1.3.4")
    assert current.update_available is False


def test_exe_update_requires_newer_version(monkeypatch):
    monkeypatch.setattr(updater, "detect_mode", lambda root=None: "exe")
    monkeypatch.setattr(updater, "local_commit", lambda root=None: "aaa")
    monkeypatch.setattr(updater, "fetch_remote_commit", lambda: ("bbb", "msg", "2026-01-01"))
    monkeypatch.setattr(
        updater,
        "fetch_latest_release",
        lambda: {
            "tag_name": "latest",
            "html_url": "https://example.com",
            "assets": [
                {"name": "version.json", "browser_download_url": "https://example.com/version.json"},
                {"name": "SpecForge.exe", "browser_download_url": "https://example.com/SpecForge.exe"},
            ],
        },
    )
    monkeypatch.setattr(updater, "_http_json", lambda url: {"version": "1.3.3", "commit": "bbb"})

    info = updater.check_for_updates("1.3.3")
    assert info.update_available is False
    assert info.can_update_exe is False


def test_apply_update_refuses_when_current(monkeypatch):
    info = updater.UpdateInfo(
        local_version="1.3.3",
        local_commit="aaa",
        remote_commit="aaa",
        remote_message="msg",
        remote_date=None,
        release_tag="latest",
        release_url=None,
        update_available=False,
        mode="git",
        detail="You are up to date.",
        remote_version="1.3.3",
        can_update_exe=False,
    )
    monkeypatch.setattr(updater, "check_for_updates", lambda version: info)
    try:
        updater.apply_update("1.3.3")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "up to date" in str(exc).lower() or "newer" in str(exc).lower()


def test_verify_downloaded_exe_rejects_tiny_or_non_pe(tmp_path):
    bad = tmp_path / "SpecForge.exe"
    bad.write_bytes(b"not an exe")
    try:
        updater.verify_downloaded_exe(bad)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "bytes" in str(exc).lower() or "mz" in str(exc).lower()


def test_verify_downloaded_exe_accepts_mz_and_sha(tmp_path):
    path = tmp_path / "SpecForge.exe"
    payload = b"MZ" + (b"\0" * 8_000_010)
    path.write_bytes(payload)
    digest = updater._sha256_file(path)
    updater.verify_downloaded_exe(path, expected_sha256=digest)


def test_windows_replace_script_contains_settle_and_copy(tmp_path):
    exe = tmp_path / "SpecForge.exe"
    new = tmp_path / "SpecForge.exe.new"
    exe.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    script = updater._windows_replace_script(exe, new, "abc123")
    body = script.read_text(encoding="utf-8")
    assert "tasklist" in body
    assert "copy /Y" in body
    assert "Unblock-File" in body
    assert "timeout /t 3" in body
