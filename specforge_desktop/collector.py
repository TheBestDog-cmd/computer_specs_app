"""Collect live host inventory and usage metrics."""

from __future__ import annotations

import json
import os
import platform
import shutil
import struct
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psutil


def _process_bitness() -> int:
    """Return 32 or 64 for the running interpreter / frozen exe."""
    return struct.calcsize("P") * 8


def _ensure_full_cpu_affinity() -> None:
    """Clear accidental CPU affinity masks so per-core samples cover all logical CPUs.

    A restricted affinity (or a 32-bit process on some Windows setups) can make
    psutil.cpu_percent(percpu=True) report fewer cores than the machine has.
    """
    try:
        proc = psutil.Process()
        if not hasattr(proc, "cpu_affinity"):
            return
        affinity = proc.cpu_affinity()
        logical = psutil.cpu_count(logical=True) or 0
        if not affinity or logical <= 0:
            return
        if len(affinity) < logical:
            proc.cpu_affinity(list(range(logical)))
    except (AttributeError, NotImplementedError, OSError, psutil.Error):
        return


def _subprocess_kwargs() -> dict[str, Any]:
    """Hide console windows spawned by child processes on Windows."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if platform.system() == "Windows":
        # CREATE_NO_WINDOW prevents a CMD flash on every nvidia-smi / nvcc call.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _run_capture(cmd: list[str], *, timeout: float = 3.0) -> str:
    return subprocess.check_output(
        cmd,
        text=True,
        timeout=timeout,
        **_subprocess_kwargs(),
    )


_CUDA_CACHE: dict[str, Any] | None = None
_NVIDIA_SMI: str | None | bool = False  # False = unset, None = missing, str = path
_AMD_SMI: str | None | bool = False
_WIN_TEMP_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_WIN_TEMP_TTL_SEC = 2.0


def _nvidia_smi_path() -> str | None:
    """Locate nvidia-smi, including common Windows install paths outside PATH."""
    global _NVIDIA_SMI
    if _NVIDIA_SMI is False:
        found = shutil.which("nvidia-smi")
        if not found and platform.system() == "Windows":
            candidates = [
                Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
                Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
                Path(r"C:\Windows\System32\nvidia-smi.exe"),
            ]
            for path in candidates:
                if path.is_file():
                    found = str(path)
                    break
        _NVIDIA_SMI = found
    return _NVIDIA_SMI  # type: ignore[return-value]


def _amd_smi_path() -> str | None:
    global _AMD_SMI
    if _AMD_SMI is False:
        found = shutil.which("amd-smi") or shutil.which("rocm-smi")
        _AMD_SMI = found
    return _AMD_SMI  # type: ignore[return-value]


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
    smi = _nvidia_smi_path()
    if not smi:
        return []
    query = (
        "name,driver_version,memory.total,memory.used,memory.free,"
        "utilization.gpu,utilization.memory,temperature.gpu,power.draw,power.limit,"
        "clocks.sm,clocks.mem"
    )
    try:
        out = _run_capture(
            [
                smi,
                f"--query-gpu={query}",
                "--format=csv,noheader,nounits",
            ],
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
    global _CUDA_CACHE
    if _CUDA_CACHE is not None:
        return dict(_CUDA_CACHE)

    info: dict[str, Any] = {"toolkit_detected": False, "nvcc_version": None, "note": None}
    nvcc = shutil.which("nvcc")
    if nvcc:
        try:
            out = _run_capture([nvcc, "--version"], timeout=3)
            for line in out.splitlines():
                if "release" in line.lower():
                    info["nvcc_version"] = line.strip()
                    info["toolkit_detected"] = True
                    break
        except (subprocess.SubprocessError, OSError):
            pass
    if not info["toolkit_detected"]:
        info["note"] = "CUDA toolkit / nvcc not detected on PATH. NVIDIA GPUs still report via nvidia-smi when present."
    _CUDA_CACHE = dict(info)
    return info


def _gpu_amd() -> list[dict[str, Any]]:
    """Best-effort AMD GPU metrics via amd-smi / rocm-smi when installed."""
    smi = _amd_smi_path()
    if not smi:
        return []
    name = Path(smi).name.lower()
    gpus: list[dict[str, Any]] = []
    try:
        if name.startswith("amd-smi"):
            out = _run_capture(
                [smi, "metric", "--field", "gpu,temp,power,usage", "--format", "csv"],
                timeout=4,
            )
            # Flexible CSV parse: keep any numeric temp-like field.
            for line in out.strip().splitlines():
                if not line or line.lower().startswith("gpu"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                if not parts:
                    continue
                temp = None
                for part in parts[1:]:
                    val = _num(part.replace("C", "").replace("c", "").strip())
                    if val is not None and 0 < val < 120:
                        temp = val
                        break
                gpus.append(
                    {
                        "vendor": "AMD",
                        "name": parts[0] or "AMD GPU",
                        "cuda_available": False,
                        "temp_c": temp,
                        "note": "AMD metrics via amd-smi (limited fields).",
                    }
                )
        else:
            out = _run_capture([smi, "--showtemp"], timeout=4)
            temp = None
            for line in out.splitlines():
                lower = line.lower()
                if "temperature" in lower or "temp" in lower:
                    for token in line.replace("=", " ").replace(":", " ").split():
                        val = _num(token.replace("c", "").replace("C", ""))
                        if val is not None and 0 < val < 120:
                            temp = val
                            break
                if temp is not None:
                    break
            gpus.append(
                {
                    "vendor": "AMD",
                    "name": "AMD GPU",
                    "cuda_available": False,
                    "temp_c": temp,
                    "note": "AMD temperature via rocm-smi.",
                }
            )
    except (subprocess.SubprocessError, OSError):
        return []
    return gpus


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


def _psutil_temperatures() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False) or {}
    except Exception:
        return rows
    for name, entries in temps.items():
        for entry in entries:
            if entry.current is None:
                continue
            rows.append(
                {
                    "sensor": name,
                    "label": entry.label or name,
                    "current_c": float(entry.current),
                    "high_c": entry.high,
                    "critical_c": entry.critical,
                    "source": "psutil",
                    "kind": _classify_temp_label(entry.label or name),
                }
            )
    return rows


def _classify_temp_label(label: str) -> str:
    lower = (label or "").lower()
    if any(token in lower for token in ("gpu", "nvidia", "radeon", "geforce", "quadro", "rtx", "gtx", "rx ")):
        return "gpu"
    if any(token in lower for token in ("cpu", "core", "package", "tctl", "tdie", "pentium", "ryzen", "intel", "amd")):
        return "cpu"
    if "acpi" in lower or "thermal zone" in lower or "tz" == lower:
        return "acpi"
    return "other"


def _windows_temperatures() -> list[dict[str, Any]]:
    """Collect Windows temps via Libre/Open Hardware Monitor WMI and ACPI zones."""
    global _WIN_TEMP_CACHE
    now = time.time()
    if _WIN_TEMP_CACHE and now - _WIN_TEMP_CACHE[0] < _WIN_TEMP_TTL_SEC:
        return [dict(row) for row in _WIN_TEMP_CACHE[1]]

    # Single PowerShell pass — avoids flashing consoles via CREATE_NO_WINDOW.
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$rows = New-Object System.Collections.Generic.List[object]

function Add-TempRow($sensor, $label, $current, $source) {
  if ($null -eq $current) { return }
  try { $c = [double]$current } catch { return }
  if ($c -lt -40 -or $c -gt 150) { return }
  $rows.Add([pscustomobject]@{
    sensor = $sensor
    label = [string]$label
    current_c = [math]::Round($c, 1)
    source = $source
  }) | Out-Null
}

foreach ($ns in @('root/LibreHardwareMonitor', 'root/OpenHardwareMonitor')) {
  try {
    $sensors = Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction SilentlyContinue |
      Where-Object { $_.SensorType -eq 'Temperature' -and $null -ne $_.Value }
    foreach ($s in $sensors) {
      $label = if ($s.Name) { $s.Name } else { $s.Identifier }
      if ($s.Identifier) { $label = "$label ($($s.Identifier))" }
      Add-TempRow ($ns.Split('/')[-1]) $label $s.Value ($ns.Split('/')[-1])
    }
  } catch {}
}

try {
  $zones = Get-CimInstance -Namespace root/WMI -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue
  foreach ($z in $zones) {
    $c = ([double]$z.CurrentTemperature / 10.0) - 273.15
    $label = if ($z.InstanceName) { $z.InstanceName } else { 'ACPI Thermal Zone' }
    Add-TempRow 'ACPI' $label $c 'MSAcpi_ThermalZoneTemperature'
  }
} catch {}

if ($rows.Count -eq 0) { '[]' } else { $rows | ConvertTo-Json -Compress }
"""
    rows: list[dict[str, Any]] = []
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        _WIN_TEMP_CACHE = (now, [])
        return []
    try:
        out = _run_capture(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            timeout=5,
        ).strip()
        if not out:
            _WIN_TEMP_CACHE = (now, [])
            return []

        payload = json.loads(out)
        if isinstance(payload, dict):
            payload = [payload]
        for item in payload or []:
            current = item.get("current_c")
            if current is None:
                continue
            label = str(item.get("label") or item.get("sensor") or "Sensor")
            rows.append(
                {
                    "sensor": str(item.get("sensor") or "Windows"),
                    "label": label,
                    "current_c": float(current),
                    "high_c": None,
                    "critical_c": None,
                    "source": str(item.get("source") or "Windows"),
                    "kind": _classify_temp_label(label),
                }
            )
    except (subprocess.SubprocessError, OSError, ValueError):
        rows = []

    _WIN_TEMP_CACHE = (now, list(rows))
    return [dict(row) for row in rows]


def _temps_from_gpus(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, gpu in enumerate(gpus):
        temp = gpu.get("temp_c")
        if temp is None:
            continue
        vendor = gpu.get("vendor") or "GPU"
        name = gpu.get("name") or f"GPU {idx}"
        rows.append(
            {
                "sensor": str(vendor),
                "label": f"{vendor} GPU: {name}",
                "current_c": float(temp),
                "high_c": None,
                "critical_c": None,
                "source": "nvidia-smi" if vendor == "NVIDIA" else "gpu-tool",
                "kind": "gpu",
            }
        )
    return rows


def _dedupe_temps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, float]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("source")), str(row.get("label")), round(float(row["current_c"]), 1))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _pick_primary_temp(rows: list[dict[str, Any]], kind: str) -> float | None:
    preferred_labels = {
        "cpu": ("cpu package", "package", "tctl", "tdie", "cpu", "core average", "core max"),
        "gpu": ("gpu", "nvidia", "radeon", "edge", "hotspot"),
    }
    candidates = [r for r in rows if r.get("kind") == kind and r.get("current_c") is not None]
    if not candidates and kind == "cpu":
        # ACPI zones are a weak fallback when nothing else reports CPU.
        candidates = [r for r in rows if r.get("kind") == "acpi" and r.get("current_c") is not None]
    if not candidates:
        return None
    prefs = preferred_labels.get(kind, ())
    for pref in prefs:
        for row in candidates:
            if pref in str(row.get("label", "")).lower():
                return float(row["current_c"])
    return float(candidates[0]["current_c"])


def _temperature_guidance(*, platform_name: str, rows: list[dict[str, Any]], gpus: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    has_cpu = any(r.get("kind") == "cpu" for r in rows) or any(r.get("kind") == "acpi" for r in rows)
    has_gpu = any(r.get("kind") == "gpu" for r in rows) or any(g.get("temp_c") is not None for g in gpus)
    nvidia_present = any((g.get("vendor") or "").upper() == "NVIDIA" for g in gpus)
    nvidia_smi = _nvidia_smi_path()

    if platform_name == "Windows":
        if not has_cpu:
            notes.append(
                "CPU temp unavailable: Windows does not expose CPU package sensors to normal apps. "
                "Install LibreHardwareMonitor (or OpenHardwareMonitor), run it (often as Admin), "
                "and keep it open so SpecForge can read its WMI sensors."
            )
            notes.append(
                "Optional fallback: ACPI thermal zones via WMI sometimes appear when SpecForge is run as Administrator, "
                "but they are often inaccurate board zones — not true CPU package temp."
            )
        if not has_gpu:
            if nvidia_smi:
                notes.append(
                    "GPU temp unavailable even though nvidia-smi was found. "
                    "Confirm the NVIDIA driver is working (`nvidia-smi` in a terminal)."
                )
            else:
                notes.append(
                    "GPU temp unavailable: install/update NVIDIA drivers so `nvidia-smi` works "
                    "(usually in PATH or System32). AMD: install amd-smi, or keep LibreHardwareMonitor running."
                )
            if nvidia_present and not nvidia_smi:
                notes.append("An NVIDIA GPU was detected earlier, but nvidia-smi is not callable from SpecForge.")
    else:
        if not has_cpu:
            if not rows:
                notes.append(
                    "CPU temp unavailable: no hwmon/thermal sensors exposed on this host "
                    "(common on VMs/cloud images). On bare metal Linux, install lm-sensors "
                    "and run `sensors-detect`, or ensure `/sys/class/hwmon` is populated."
                )
            else:
                notes.append(
                    "CPU temperature sensors were not found in hwmon/psutil "
                    "(only non-CPU sensors were reported)."
                )
        if not has_gpu:
            if nvidia_smi:
                notes.append(
                    "GPU temp unavailable even though nvidia-smi was found. "
                    "Confirm the NVIDIA driver is working (`nvidia-smi` in a terminal)."
                )
            else:
                notes.append(
                    "GPU temperature needs nvidia-smi (NVIDIA) or vendor tools "
                    "(AMD ROCm / amd-smi)."
                )
    return notes


def _temperatures(gpus: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gpus = gpus or []
    rows: list[dict[str, Any]] = []
    rows.extend(_psutil_temperatures())
    if platform.system() == "Windows":
        rows.extend(_windows_temperatures())
    rows.extend(_temps_from_gpus(gpus))
    rows = _dedupe_temps(rows)

    # Prefer useful ordering: CPU-ish first, then GPU, then other.
    kind_rank = {"cpu": 0, "acpi": 1, "gpu": 2, "other": 3}
    rows.sort(key=lambda r: (kind_rank.get(str(r.get("kind")), 9), str(r.get("label", ""))))

    cpu_c = _pick_primary_temp(rows, "cpu")
    gpu_c = _pick_primary_temp(rows, "gpu")
    if gpu_c is None:
        for g in gpus:
            if g.get("temp_c") is not None:
                gpu_c = float(g["temp_c"])
                break

    status = {
        "cpu_c": cpu_c,
        "gpu_c": gpu_c,
        "available": bool(rows),
        "notes": _temperature_guidance(platform_name=platform.system(), rows=rows, gpus=gpus),
        "sources": sorted({str(r.get("source")) for r in rows if r.get("source")}),
    }
    return rows, status


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
    temperature_status: dict[str, Any] = field(default_factory=dict)
    processes_top: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpecsCollector:
    def __init__(self) -> None:
        self._prev_net = psutil.net_io_counters()
        self._prev_disk = psutil.disk_io_counters()
        self._prev_time = time.time()
        self._cached_procs: list[dict[str, Any]] = []
        self._procs_at = 0.0
        _ensure_full_cpu_affinity()
        # Prime CPU percent (overall + every logical core)
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)

    def collect(self) -> Snapshot:
        now = time.time()
        dt = max(now - self._prev_time, 1e-6)

        cpu_freq = psutil.cpu_freq()
        logical_cores = psutil.cpu_count(logical=True)
        per_core = list(psutil.cpu_percent(interval=None, percpu=True) or [])
        # If affinity was tightened after init, re-prime and resample all logical cores.
        if logical_cores and len(per_core) < logical_cores:
            _ensure_full_cpu_affinity()
            psutil.cpu_percent(interval=None, percpu=True)
            primed = list(psutil.cpu_percent(interval=None, percpu=True) or [])
            if len(primed) >= len(per_core):
                per_core = primed
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
            gpus = _gpu_amd()
        if not gpus:
            gpus = _gpus_fallback()
        if not gpus:
            gpus = [
                {
                    "vendor": "None",
                    "name": "No discrete GPU detected",
                    "cuda_available": False,
                    "temp_c": None,
                    "note": (
                        "Install NVIDIA drivers (nvidia-smi) for GPU temp/CUDA metrics, "
                        "or AMD amd-smi / LibreHardwareMonitor for Radeon temps."
                    ),
                }
            ]

        temperatures, temperature_status = _temperatures(gpus)
        # Surface primary temps on CPU dict for UI convenience.
        cpu_temp_c = temperature_status.get("cpu_c")
        gpu_temp_c = temperature_status.get("gpu_c")

        # Top processes are relatively expensive on Windows; refresh every ~2s.
        if now - self._procs_at >= 2.0 or not self._cached_procs:
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
            self._cached_procs = procs[:8]
            self._procs_at = now
        procs = self._cached_procs

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
                "model": _cpu_model(),
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": logical_cores,
                "usage_percent": psutil.cpu_percent(interval=None),
                "per_core_percent": per_core,
                "process_bitness": _process_bitness(),
                "freq_current_mhz": cpu_freq.current if cpu_freq else None,
                "freq_max_mhz": cpu_freq.max if cpu_freq else None,
                "load_avg": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
                "temp_c": cpu_temp_c,
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
            temperatures=temperatures,
            temperature_status={
                **temperature_status,
                "gpu_c": gpu_temp_c,
            },
            processes_top=list(procs),
        )


_CPU_MODEL_CACHE: str | None = None


def _looks_like_cpu_brand(value: str | None) -> bool:
    if not value:
        return False
    cleaned = " ".join(str(value).split()).strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    junk = {
        "x86_64",
        "amd64",
        "i386",
        "i686",
        "arm64",
        "aarch64",
        "unknown",
        "unknown cpu",
    }
    if lower in junk:
        return False
    # Windows platform.processor() often returns this useless Family/Model string.
    if lower.startswith("intel64 family") or lower.startswith("amd64 family"):
        return False
    if "family" in lower and "model" in lower and "stepping" in lower:
        return False
    return True


def _cpu_model_from_proc() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                value = line.split(":", 1)[1].strip()
                if _looks_like_cpu_brand(value):
                    return value
    except OSError:
        return None
    return None


def _cpu_model_from_windows_registry() -> str | None:
    if platform.system() != "Windows":
        return None
    try:
        import winreg  # stdlib on Windows

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        value = " ".join(str(value).split()).strip()
        return value if _looks_like_cpu_brand(value) else None
    except Exception:
        return None


def _cpu_model_from_windows_wmi() -> str | None:
    if platform.system() != "Windows":
        return None
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    commands: list[list[str]] = []
    if powershell:
        commands.append(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)",
            ]
        )
    if shutil.which("wmic"):
        commands.append(["wmic", "cpu", "get", "Name"])
    for cmd in commands:
        try:
            out = _run_capture(cmd, timeout=4).strip()
        except (subprocess.SubprocessError, OSError, FileNotFoundError):
            continue
        lines = [ln.strip() for ln in out.splitlines() if ln.strip() and ln.strip().lower() != "name"]
        if lines and _looks_like_cpu_brand(lines[0]):
            return " ".join(lines[0].split())
    return None


def _cpu_model() -> str:
    """Return a human CPU brand string (cached)."""
    global _CPU_MODEL_CACHE
    if _CPU_MODEL_CACHE:
        return _CPU_MODEL_CACHE

    for value in (
        _cpu_model_from_proc(),
        _cpu_model_from_windows_registry(),
        _cpu_model_from_windows_wmi(),
        platform.processor(),
        os.environ.get("PROCESSOR_IDENTIFIER"),
    ):
        if _looks_like_cpu_brand(value):
            _CPU_MODEL_CACHE = " ".join(str(value).split())
            return _CPU_MODEL_CACHE
    _CPU_MODEL_CACHE = "Unknown CPU"
    return _CPU_MODEL_CACHE
