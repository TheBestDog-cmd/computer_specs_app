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
    monkeypatch.setattr(
        updater,
        "fetch_published_version_meta",
        lambda: {"version": "1.3.4", "commit": "bbb", "tag": "latest", "sha256": "abc"},
    )

    def boom(*_a, **_k):
        raise AssertionError("REST API should not be needed when CDN meta is present")

    monkeypatch.setattr(updater, "fetch_remote_commit", boom)
    monkeypatch.setattr(updater, "fetch_latest_release", boom)

    newer = updater.check_for_updates("1.3.3")
    assert newer.update_available is True
    assert newer.remote_version == "1.3.4"
    assert newer.exe_asset_url == updater.RELEASE_EXE_URL

    current = updater.check_for_updates("1.3.4")
    assert current.update_available is False


def test_exe_update_requires_newer_version(monkeypatch):
    monkeypatch.setattr(updater, "detect_mode", lambda root=None: "exe")
    monkeypatch.setattr(updater, "local_commit", lambda root=None: "aaa")
    monkeypatch.setattr(
        updater,
        "fetch_published_version_meta",
        lambda: {"version": "1.3.3", "commit": "bbb", "tag": "latest", "sha256": "abc"},
    )

    def boom(*_a, **_k):
        raise AssertionError("exe checks must not call the GitHub REST API")

    monkeypatch.setattr(updater, "fetch_remote_commit", boom)
    monkeypatch.setattr(updater, "fetch_latest_release", boom)

    info = updater.check_for_updates("1.3.3")
    assert info.update_available is False
    assert info.can_update_exe is False


def test_exe_check_skips_github_api(monkeypatch):
    monkeypatch.setattr(updater, "detect_mode", lambda root=None: "exe")
    monkeypatch.setattr(updater, "local_commit", lambda root=None: None)
    monkeypatch.setattr(
        updater,
        "fetch_published_version_meta",
        lambda: {
            "version": "1.3.12",
            "commit": "cccc",
            "tag": "latest",
            "sha256": "deadbeef",
        },
    )

    def boom(*_a, **_k):
        raise AssertionError("exe checks must not call the GitHub REST API")

    monkeypatch.setattr(updater, "fetch_remote_commit", boom)
    monkeypatch.setattr(updater, "fetch_latest_release", boom)

    info = updater.check_for_updates("1.3.11")
    assert info.update_available is True
    assert info.can_update_exe is True
    assert info.remote_version == "1.3.12"
    assert info.exe_asset_url == updater.RELEASE_EXE_URL
    assert info.exe_sha256 == "deadbeef"
    assert updater.EXE_ASSET_NAME == "SpecForge-Setup.exe"


def test_release_json_uses_download_safe_accept(monkeypatch):
    """Release CDN must not send Accept: application/json (GitHub 403s that)."""
    seen: dict[str, str] = {}

    class _Resp:
        def read(self) -> bytes:
            return b'{"version":"9.9.9"}'

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_urlopen(req, timeout=20):  # noqa: ARG001
        # urllib stores header names title-cased.
        seen["accept"] = req.get_header("Accept") or ""
        seen["ua"] = req.get_header("User-agent") or req.get_header("User-Agent") or ""
        return _Resp()

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    data = updater._http_json(updater.RELEASE_VERSION_URL)
    assert data["version"] == "9.9.9"
    assert seen["accept"] == "*/*"
    assert "application/json" not in seen["accept"].lower()
    assert "github" not in seen["accept"].lower()


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
    script = updater._windows_replace_script(exe, new, "abc123", pid=4242)
    assert script.suffix == ".ps1"
    body = script.read_text(encoding="utf-8")
    assert "$pidToWait = 4242" in body
    assert "Timeout 25" in body
    assert "Stop-Process -Name 'SpecForge'" in body
    assert "_MEI*" in body
    assert "Move-Item" in body
    assert "Start-Process" in body
    assert "Zone.Identifier" in body
    assert "extractRoot" in body
    assert "tasklist" not in body
    assert ":wait_proc" not in body
