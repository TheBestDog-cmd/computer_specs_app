from specforge_desktop.collector import Snapshot
from specforge_desktop.gui import (
    SCROLL_PAUSE_SEC,
    build_dashboard_text,
    format_core_lines,
    format_system_lines,
    format_temperature_lines,
)


def test_scroll_pause_is_substantial():
    assert SCROLL_PAUSE_SEC >= 0.5


def test_format_core_lines_lists_all_small_counts():
    lines = format_core_lines([10.0, 20.0, 30.0], expected=3)
    assert len(lines) == 3
    assert "Core 00" in lines[0]
    assert "Core 02" in lines[2]


def test_format_core_lines_compacts_high_counts():
    cores = [float(i % 50) for i in range(32)]
    lines = format_core_lines(cores, expected=32, dense_after=16)
    joined = "\n".join(lines)
    assert "32 logical" in joined
    assert "omitted while monitoring" in joined
    assert "Core 00" in joined
    assert "Core 31" in joined
    assert joined.count("Core ") < 32


def test_format_core_lines_reports_affinity_gap():
    lines = format_core_lines([1.0, 2.0], expected=8)
    assert any("only 2 of 8" in line for line in lines)


def test_format_system_lines():
    snap = Snapshot(
        collected_at=1.0,
        system={
            "hostname": "box",
            "os": "Windows",
            "release": "10",
            "arch": "AMD64",
            "uptime_sec": 65,
            "python": "3.11",
        },
    )
    text = "\n".join(format_system_lines(snap))
    assert "Hostname     box" in text
    assert "OS           Windows" in text
    assert "1m 5s" in text
    assert "Python       3.11" in text


def test_format_temperature_lines_groups_all_sensors():
    snap = Snapshot(
        collected_at=1.0,
        temperatures=[
            {"label": "CPU Package", "current_c": 55.0, "source": "lhm", "kind": "cpu", "high_c": 95},
            {"label": "GPU Core", "current_c": 60.0, "source": "nvidia-smi", "kind": "gpu"},
            {"label": "TZ00", "current_c": 40.0, "source": "acpi", "kind": "acpi"},
            {"label": "Chipset", "current_c": 42.0, "source": "lhm", "kind": "other"},
        ],
        temperature_status={
            "cpu_c": 55.0,
            "gpu_c": 60.0,
            "sources": ["acpi", "lhm", "nvidia-smi"],
            "notes": ["Install LibreHardwareMonitor for CPU package temp."],
        },
    )
    text = "\n".join(format_temperature_lines(snap))
    assert "=== Temperatures ===" in text
    assert "-- CPU --" in text
    assert "-- GPU --" in text
    assert "-- Board / ACPI --" in text
    assert "-- Other sensors --" in text
    assert "CPU Package" in text
    assert "GPU Core" in text
    assert "TZ00" in text
    assert "Chipset" in text
    assert "high 95" in text
    assert "How to enable missing temps:" in text
    assert "LibreHardwareMonitor" in text


def test_format_temperature_lines_empty_state_panel_wording():
    """Top Temperatures panel (no heading) always shows CPU/GPU + enable notes."""
    snap = Snapshot(
        collected_at=1.0,
        temperatures=[],
        temperature_status={
            "cpu_c": None,
            "gpu_c": None,
            "sources": [],
            "notes": [
                "CPU temp unavailable: install LibreHardwareMonitor.",
                "GPU temp unavailable: install NVIDIA drivers so nvidia-smi works.",
            ],
        },
    )
    text = "\n".join(format_temperature_lines(snap, include_heading=False))
    assert "=== Temperatures ===" not in text
    assert "CPU temp     unavailable" in text
    assert "GPU temp     unavailable" in text
    assert "No live sensor readings yet." in text
    assert "How to enable missing temps:" in text
    assert "LibreHardwareMonitor" in text
    assert "nvidia-smi" in text
    # Must not be the old bare single-line empty message alone.
    assert "No temperature sensors exposed on this host." not in text


def test_format_temperature_lines_fallback_notes_when_status_empty():
    snap = Snapshot(
        collected_at=1.0,
        temperatures=[],
        temperature_status={"cpu_c": None, "gpu_c": None, "sources": [], "notes": []},
    )
    text = "\n".join(format_temperature_lines(snap, include_heading=False))
    assert "CPU temp     unavailable" in text
    assert "GPU temp     unavailable" in text
    assert "No live sensor readings yet." in text
    assert "How to enable missing temps:" in text
    assert "LibreHardwareMonitor" in text or "lm-sensors" in text
    assert "nvidia-smi" in text


def _sample_snap(**overrides) -> Snapshot:
    base = dict(
        collected_at=1.0,
        system={
            "hostname": "box",
            "os": "Windows",
            "release": "10",
            "arch": "AMD64",
            "uptime_sec": 65,
            "python": "3.11",
        },
        cpu={
            "model": "TestCPU",
            "physical_cores": 4,
            "logical_cores": 8,
            "freq_current_mhz": 3000,
            "freq_max_mhz": 4000,
            "temp_c": 55.0,
            "load_avg": [],
            "per_core_percent": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            "usage_percent": 12.0,
        },
        memory={"used": "1 GB", "total": "8 GB", "percent": 12.5, "available": "7 GB"},
        swap={"used": "0 B", "total": "1 GB", "percent": 0},
        disks=[{"mount": "C:\\", "used": "100 GB", "total": "500 GB", "percent": 20, "fstype": "NTFS"}],
        disk_io={"read_human_s": "1 MB/s", "write_human_s": "2 MB/s"},
        gpu=[{
            "vendor": "NVIDIA",
            "name": "Test GPU",
            "cuda_available": True,
            "temp_c": 60.0,
            "driver": "1",
            "memory_used_mb": 1,
            "memory_total_mb": 8,
            "util_gpu_percent": 3,
            "util_mem_percent": 4,
            "power_draw_w": 50,
            "power_limit_w": 100,
            "clock_sm_mhz": 1000,
            "clock_mem_mhz": 2000,
        }],
        cuda={"toolkit_detected": False, "note": "no toolkit"},
        temperatures=[
            {"label": "CPU Package", "current_c": 55.0, "source": "test", "kind": "cpu"},
            {"label": "GPU Core", "current_c": 60.0, "source": "test", "kind": "gpu"},
        ],
        temperature_status={"cpu_c": 55.0, "gpu_c": 60.0, "sources": ["test"], "notes": []},
        network=[{"name": "eth0", "family": "IPv4", "address": "1.2.3.4", "isup": True}],
        net_io={"recv_human_s": "1 KB/s", "sent_human_s": "2 KB/s"},
        power=[{"name": "Battery", "type": "Battery", "status": "Discharging", "capacity": 80}],
        processes_top=[{"pid": 1, "cpu_percent": 1.0, "memory_percent": 2.0, "name": "idle"}],
    )
    base.update(overrides)
    return Snapshot(**base)


def test_build_dashboard_text_includes_sections():
    text = build_dashboard_text(_sample_snap())
    for heading in (
        "=== System ===",
        "=== CPU / Cores ===",
        "=== Memory & Swap ===",
        "=== Disks & I/O ===",
        "=== GPU / CUDA ===",
        "=== Temperatures ===",
        "=== Network ===",
        "=== Top processes ===",
    ):
        assert heading in text
    assert "=== PSU / Power ===" not in text
    assert "Power data unavailable" not in text
    assert "-- CPU --" in text
    assert "CPU Package" in text
    assert "GPU Core" in text
    assert "Core 07" in text
    assert "TestCPU" in text


def test_build_dashboard_text_omits_top_row_panels_when_flagged():
    """Live dashboard below System|Temperatures top row omits those sections."""
    text = build_dashboard_text(
        _sample_snap(),
        include_system=False,
        include_temperatures=False,
    )
    assert "=== System ===" not in text
    assert "=== Temperatures ===" not in text
    assert "=== CPU / Cores ===" in text
    assert "=== Memory & Swap ===" in text
    assert "=== Disks & I/O ===" in text
    assert "=== GPU / CUDA ===" in text
    assert "=== Network ===" in text
    assert "=== Top processes ===" in text
    assert "TestCPU" in text
    # System hostname should not appear as a System block line, but CPU model should.
    assert "Hostname     box" not in text
