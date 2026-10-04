"""Collect live host inventory and usage metrics."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psutil


def _bytes_human(n: float | int | None) -> str:
    if n is None:
        return "n/a"
    n = float(n)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    while n >= 1024 and idx < len(units) - 1:
        n /= 1024
        idx += 1
    return f"{n:.0f} {units[idx]}" if idx == 0 else f"{n:.2f} {units[idx]}"


def _read_os_pretty() -> str:
    try:
        data = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key] = value.strip().strip('"')
        return data.get("PRETTY_NAME") or platform.platform()
    except OSError:
        return platform.platform()


def _power_supply() -> list[dict[str, Any]]:
    root = Path("/sys/class/power_supply")
    if not root.exists():
        return [
            {
                "name": "PSU / Power",
                "status": "Unavailable",
                "detail": "No power_supply sysfs entries (common on VMs/desktops without exposed PSU sensors).",
            }
        ]
    devices = []
    for entry in sorted(root.iterdir()):
        try:
            type_path = entry / "type"
            present = (entry / "present").read_text().strip() if (entry / "present").exists() else "1"
            if present == "0":
                continue
            kind = type_path.read_text().strip() if type_path.exists() else "Unknown"
            info: dict[str, Any] = {"name": entry.name, "type": kind}
            for key in ("status", "capacity", "capacity_level", "voltage_now", "current_now", "power_now", "online", "manufacturer", "model_name"):
                path = entry / key
                if path.exists():
                    raw = path.read_text().strip()
                    if key in {"voltage_now", "current_now", "power_now"} and raw.isdigit():
                        # µV / µA / µW → friendlier units
                        value = int(raw)
                        if key == "voltage_now":
                            info["voltage_v"] = round(value / 1_000_000, 2)
                        elif key == "current_now":
                            info["current_a"] = round(value / 1_000_000, 3)
                        else:
                            info["power_w"] = round(value / 1_000_000, 2)
                    else:
                        info[key] = raw
            if "power_w" not in info and "voltage_v" in info and "current_a" in info:
                info["power_w"] = round(info["voltage_v"] * info["current_a"], 2)
            devices.append(info)
        except OSError:
            continue
    if not devices:
        devices.append(
            {
                "name": "PSU / Power",
                "status": "Unavailable",
                "detail": "Power supply class exists but no readable devices were found.",
            }
        )
    return devices


def _gpu_nvidia() -> list[dict[str, Any]]:
    if not shutil.which("nvidia-smi"):
        return []
    query = (
        "name,driver_version,memory.total,memory.used,memory.free,"
        "utilization.gpu,utilization.memory,temperature.gpu,power.draw,power.limit,"
        "clocks.sm,clocks.mem"
    )
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                f"--query-gpu={query}",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 12:
            continue
        gpus.append(
            {
                "vendor": "NVIDIA",
                "name": parts[0],
                "driver": parts[1],
                "cuda_available": True,
                "memory_total_mb": _num(parts[2]),
                "memory_used_mb": _num(parts[3]),
                "memory_free_mb": _num(parts[4]),
                "util_gpu_percent": _num(parts[5]),
                "util_mem_percent": _num(parts[6]),
                "temp_c": _num(parts[7]),
                "power_draw_w": _num(parts[8]),
                "power_limit_w": _num(parts[9]),
                "clock_sm_mhz": _num(parts[10]),
                "clock_mem_mhz": _num(parts[11]),
            }
        )
    return gpus


def _cuda_toolkit() -> dict[str, Any]:
    info: dict[str, Any] = {"toolkit_detected": False, "nvcc_version": None, "note": None}
    nvcc = shutil.which("nvcc")
    if nvcc:
        try:
            out = subprocess.check_output([nvcc, "--version"], text=True, stderr=subprocess.STDOUT, timeout=3)
            for line in out.splitlines():
                if "release" in line.lower():
                    info["nvcc_version"] = line.strip()
                    info["toolkit_detected"] = True
                    break
        except (subprocess.SubprocessError, OSError):
            pass
    if not info["toolkit_detected"]:
        info["note"] = "CUDA toolkit / nvcc not detected on PATH. NVIDIA GPUs still report via nvidia-smi when present."
    return info


def _gpus_fallback() -> list[dict[str, Any]]:
    """Best-effort non-NVIDIA discovery on Linux."""
    gpus: list[dict[str, Any]] = []
    dri = Path("/sys/class/drm")
    if dri.exists():
        for card in sorted(dri.glob("card[0-9]")):
            if "-" in card.name:
                continue
            vendor = (card / "device" / "vendor").read_text().strip() if (card / "device" / "vendor").exists() else "?"
            device = (card / "device" / "device").read_text().strip() if (card / "device" / "device").exists() else "?"
            gpus.append(
                {
                    "vendor": "DRM",
                    "name": f"{card.name} (vendor={vendor} device={device})",
                    "cuda_available": False,
                    "note": "Basic DRM adapter — detailed utilization requires vendor tools (nvidia-smi / rocm-smi).",
                }
            )
    return gpus


def _num(value: str) -> float | None:
    try:
        if value in {"", "[N/A]", "N/A", "None"}:
            return None
        return float(value)
    except ValueError:
        return None


def _temperatures() -> list[dict[str, Any]]:
    rows = []
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False) or {}
    except Exception:
        return rows
    for name, entries in temps.items():
        for entry in entries:
            rows.append(
                {
                    "sensor": name,
                    "label": entry.label or name,
                    "current_c": entry.current,
                    "high_c": entry.high,
                    "critical_c": entry.critical,
                }
            )
    return rows


@dataclass
class Snapshot:
    collected_at: float
    system: dict[str, Any] = field(default_factory=dict)
    cpu: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    swap: dict[str, Any] = field(default_factory=dict)
    disks: list[dict[str, Any]] = field(default_factory=list)
    disk_io: dict[str, Any] = field(default_factory=dict)
    network: list[dict[str, Any]] = field(default_factory=list)
    net_io: dict[str, Any] = field(default_factory=dict)
    gpu: list[dict[str, Any]] = field(default_factory=list)
    cuda: dict[str, Any] = field(default_factory=dict)
    power: list[dict[str, Any]] = field(default_factory=list)
    temperatures: list[dict[str, Any]] = field(default_factory=list)
    processes_top: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpecsCollector:
    def __init__(self) -> None:
        self._prev_net = psutil.net_io_counters()
        self._prev_disk = psutil.disk_io_counters()
        self._prev_time = time.time()
        # Prime CPU percent
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)

    def collect(self) -> Snapshot:
        now = time.time()
        dt = max(now - self._prev_time, 1e-6)

        cpu_freq = psutil.cpu_freq()
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        disks = []
        seen_mounts: set[str] = set()
        interesting_fs = {
            "",
            "ext2",
            "ext3",
            "ext4",
            "xfs",
            "btrfs",
            "zfs",
            "ntfs",
            "vfat",
            "fat32",
            "apfs",
            "overlay",
            "fuseblk",
            "nfs",
            "nfs4",
            "smb",
            "cifs",
        }
        parts = list(psutil.disk_partitions(all=False))
        if not parts:
            parts = [
                p
                for p in psutil.disk_partitions(all=True)
                if (p.fstype or "").lower() in interesting_fs or p.mountpoint == "/"
            ]
        for part in parts:
            fstype = (part.fstype or "").lower()
            if part.mountpoint in seen_mounts:
                continue
            if fstype and fstype not in interesting_fs and part.mountpoint != "/":
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            if usage.total <= 0 and part.mountpoint != "/":
                continue
            seen_mounts.add(part.mountpoint)
            disks.append(
                {
                    "device": part.device,
                    "mount": part.mountpoint,
                    "fstype": part.fstype or "unknown",
                    "total": _bytes_human(usage.total),
                    "used": _bytes_human(usage.used),
                    "free": _bytes_human(usage.free),
                    "percent": usage.percent,
                }
            )
        if not disks:
            usage = psutil.disk_usage("/")
            disks.append(
                {
                    "device": "/",
                    "mount": "/",
                    "fstype": "root",
                    "total": _bytes_human(usage.total),
                    "used": _bytes_human(usage.used),
                    "free": _bytes_human(usage.free),
                    "percent": usage.percent,
                }
            )

        disk_io = psutil.disk_io_counters()
        disk_rates: dict[str, Any] = {}
        if disk_io and self._prev_disk:
            disk_rates = {
                "read_bytes_s": (disk_io.read_bytes - self._prev_disk.read_bytes) / dt,
                "write_bytes_s": (disk_io.write_bytes - self._prev_disk.write_bytes) / dt,
                "read_human_s": _bytes_human((disk_io.read_bytes - self._prev_disk.read_bytes) / dt) + "/s",
                "write_human_s": _bytes_human((disk_io.write_bytes - self._prev_disk.write_bytes) / dt) + "/s",
            }
            self._prev_disk = disk_io

        net_if = []
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, entries in addrs.items():
            st = stats.get(name)
            for entry in entries:
                family = getattr(entry.family, "name", str(entry.family))
                if family not in {"AF_INET", "AF_INET6"} and str(entry.family) not in {"2", "10", "23"}:
                    continue
                net_if.append(
                    {
                        "name": name,
                        "family": family,
                        "address": entry.address,
                        "netmask": entry.netmask,
                        "isup": bool(st.isup) if st else None,
                        "speed_mbps": st.speed if st else None,
                    }
                )

        net_io = psutil.net_io_counters()
        net_rates: dict[str, Any] = {}
        if net_io and self._prev_net:
            net_rates = {
                "bytes_sent_s": (net_io.bytes_sent - self._prev_net.bytes_sent) / dt,
                "bytes_recv_s": (net_io.bytes_recv - self._prev_net.bytes_recv) / dt,
                "sent_human_s": _bytes_human((net_io.bytes_sent - self._prev_net.bytes_sent) / dt) + "/s",
                "recv_human_s": _bytes_human((net_io.bytes_recv - self._prev_net.bytes_recv) / dt) + "/s",
            }
            self._prev_net = net_io

        gpus = _gpu_nvidia()
        if not gpus:
            gpus = _gpus_fallback()
        if not gpus:
            gpus = [
                {
                    "vendor": "None",
                    "name": "No discrete GPU detected",
                    "cuda_available": False,
                    "note": "Install NVIDIA drivers for CUDA metrics, or AMD ROCm tools for Radeon stats.",
                }
            ]

        # Top processes by CPU then memory
        procs = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                procs.append(
                    {
                        "pid": info.get("pid"),
                        "name": info.get("name") or "?",
                        "cpu_percent": info.get("cpu_percent") or 0.0,
                        "memory_percent": info.get("memory_percent") or 0.0,
                    }
                )
            except (psutil.Error, TypeError):
                continue
        procs.sort(key=lambda p: (p["cpu_percent"], p["memory_percent"]), reverse=True)

        self._prev_time = now
        return Snapshot(
            collected_at=now,
            system={
                "hostname": platform.node(),
                "os": _read_os_pretty(),
                "platform": platform.system(),
                "release": platform.release(),
                "arch": platform.machine(),
                "python": platform.python_version(),
                "boot_time": psutil.boot_time(),
                "uptime_sec": int(now - psutil.boot_time()),
            },
            cpu={
                "model": _cpu_model_fallback() or platform.processor() or "Unknown CPU",
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "usage_percent": psutil.cpu_percent(interval=None),
                "per_core_percent": per_core,
                "freq_current_mhz": cpu_freq.current if cpu_freq else None,
                "freq_max_mhz": cpu_freq.max if cpu_freq else None,
                "load_avg": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
            },
            memory={
                "total": _bytes_human(mem.total),
                "used": _bytes_human(mem.used),
                "available": _bytes_human(mem.available),
                "percent": mem.percent,
                "total_bytes": mem.total,
                "used_bytes": mem.used,
            },
            swap={
                "total": _bytes_human(swap.total),
                "used": _bytes_human(swap.used),
                "percent": swap.percent,
            },
            disks=disks,
            disk_io=disk_rates,
            network=net_if,
            net_io=net_rates,
            gpu=gpus,
            cuda=_cuda_toolkit(),
            power=_power_supply(),
            temperatures=_temperatures(),
            processes_top=procs[:8],
        )


def _cpu_model_fallback() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "Unknown CPU"
