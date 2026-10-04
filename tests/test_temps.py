from specforge_desktop import collector


def test_classify_temp_label():
    assert collector._classify_temp_label("CPU Package") == "cpu"
    assert collector._classify_temp_label("NVIDIA GeForce RTX") == "gpu"
    assert collector._classify_temp_label("ACPI Thermal Zone") == "acpi"


def test_pick_primary_temp_prefers_cpu_package():
    rows = [
        {"kind": "cpu", "label": "Core 0", "current_c": 50.0},
        {"kind": "cpu", "label": "CPU Package", "current_c": 62.5},
        {"kind": "gpu", "label": "GPU Core", "current_c": 71.0},
    ]
    assert collector._pick_primary_temp(rows, "cpu") == 62.5
    assert collector._pick_primary_temp(rows, "gpu") == 71.0


def test_temps_from_gpus_and_status_notes(monkeypatch):
    gpus = [
        {"vendor": "NVIDIA", "name": "RTX 4070", "temp_c": 54.0},
    ]
    rows = collector._temps_from_gpus(gpus)
    assert rows[0]["kind"] == "gpu"
    assert rows[0]["current_c"] == 54.0

    monkeypatch.setattr(collector, "_psutil_temperatures", lambda: [])
    monkeypatch.setattr(collector, "_windows_temperatures", lambda: [])
    monkeypatch.setattr(collector.platform, "system", lambda: "Windows")
    monkeypatch.setattr(collector, "_nvidia_smi_path", lambda: None)

    temps, status = collector._temperatures(gpus)
    assert status["gpu_c"] == 54.0
    assert status["cpu_c"] is None
    assert any("LibreHardwareMonitor" in note for note in status["notes"])
    assert any(t["kind"] == "gpu" for t in temps)


def test_collect_includes_temperature_status():
    snap = collector.SpecsCollector().collect()
    assert isinstance(snap.temperatures, list)
    assert "cpu_c" in snap.temperature_status
    assert "gpu_c" in snap.temperature_status
    assert "notes" in snap.temperature_status
    assert "temp_c" in snap.cpu


def test_linux_empty_temperature_guidance_covers_cpu_and_gpu(monkeypatch):
    monkeypatch.setattr(collector, "_nvidia_smi_path", lambda: None)
    notes = collector._temperature_guidance(platform_name="Linux", rows=[], gpus=[])
    joined = "\n".join(notes)
    assert "CPU temp unavailable" in joined
    assert "lm-sensors" in joined or "hwmon" in joined
    assert "GPU temperature" in joined
    assert "nvidia-smi" in joined
    # Prefer clear per-device guidance over a single bare host note.
    assert "No temperature sensors exposed on this host" not in joined
