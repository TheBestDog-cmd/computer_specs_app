from specforge_desktop.collector import Snapshot
from specforge_desktop.gui import (
    SCROLL_PAUSE_SEC,
    build_dashboard_text,
    format_temperature_lines,
)


def test_scroll_pause_is_substantial():
    assert SCROLL_PAUSE_SEC >= 0.5


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


def test_build_dashboard_text_includes_sections():
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
        gpu=[{"vendor": "NVIDIA", "name": "Test GPU", "cuda_available": True, "temp_c": 60.0,
              "driver": "1", "memory_used_mb": 1, "memory_total_mb": 8,
              "util_gpu_percent": 3, "util_mem_percent": 4, "power_draw_w": 50,
              "power_limit_w": 100, "clock_sm_mhz": 1000, "clock_mem_mhz": 2000}],
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
    text = build_dashboard_text(snap)
    for heading in (
        "=== System ===",
        "=== CPU / Cores ===",
        "=== Memory & Swap ===",
        "=== Disks & I/O ===",
        "=== GPU / CUDA ===",
        "=== Temperatures ===",
        "=== Network ===",
        "=== PSU / Power ===",
        "=== Top processes ===",
    ):
        assert heading in text
    assert "-- CPU --" in text
    assert "CPU Package" in text
    assert "GPU Core" in text
    assert "Core 07" in text
    assert "TestCPU" in text
    assert "Battery" in text
