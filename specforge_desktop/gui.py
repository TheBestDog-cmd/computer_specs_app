"""CustomTkinter GUI for real-time SpecForge monitoring."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Callable

import customtkinter as ctk

from specforge_desktop.collector import SpecsCollector, Snapshot


ACCENT = "#0F7A6B"
ACCENT_DEEP = "#0B5348"
INK = "#122027"
MUTED = "#4D646E"
PANEL = "#F4F8F6"
TRACK = "#D7E3DE"
WARN = "#C46B2C"


def _fmt_uptime(seconds: int) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if mins or hours or days:
        parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


class MeterRow(ctk.CTkFrame):
    def __init__(self, master, title: str, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.title = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT_DEEP)
        self.title.grid(row=0, column=0, columnspan=2, sticky="w")
        self.value = ctk.CTkLabel(self, text="—", font=ctk.CTkFont(family="monospace", size=12), text_color=MUTED)
        self.value.grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.bar = ctk.CTkProgressBar(self, height=10, progress_color=ACCENT, fg_color=TRACK)
        self.bar.grid(row=1, column=1, sticky="ew")
        self.bar.set(0)

    def update_meter(self, percent: float | None, label: str) -> None:
        pct = 0.0 if percent is None else max(0.0, min(float(percent), 100.0))
        self.bar.set(pct / 100.0)
        self.bar.configure(progress_color=WARN if pct >= 85 else ACCENT)
        self.value.configure(text=label)


class Section(ctk.CTkFrame):
    def __init__(self, master, title: str, **kwargs):
        super().__init__(master, fg_color=PANEL, corner_radius=12, border_width=1, border_color="#D5E0DB", **kwargs)
        self.title = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=15, weight="bold"), text_color=ACCENT_DEEP)
        self.title.pack(anchor="w", padx=14, pady=(12, 6))
        self.body = ctk.CTkLabel(
            self,
            text="Loading…",
            justify="left",
            anchor="nw",
            font=ctk.CTkFont(family="monospace", size=12),
            text_color=INK,
        )
        self.body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def set_text(self, text: str) -> None:
        self.body.configure(text=text)


class SpecForgeApp(ctk.CTk):
    def __init__(self, refresh_ms: int = 1000):
        super().__init__()
        self.refresh_ms = refresh_ms
        self.collector = SpecsCollector()
        self._lock = threading.Lock()
        self._latest: Snapshot | None = None
        self._running = True
        self._paused = False

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")

        self.title("SpecForge — Real-time Computer Specs")
        self.geometry("1180x820")
        self.minsize(960, 700)
        self.configure(fg_color="#E8F0EC")

        self._build_header()
        self._build_body()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._worker = threading.Thread(target=self._collect_loop, daemon=True)
        self._worker.start()
        self.after(200, self._ui_tick)

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 8))

        brand = ctk.CTkLabel(
            header,
            text="SpecForge",
            font=ctk.CTkFont(size=34, weight="bold"),
            text_color=ACCENT_DEEP,
        )
        brand.pack(anchor="w")

        subtitle = ctk.CTkLabel(
            header,
            text="Live inventory and usage for CPU, memory, disks, network, GPU/CUDA, temperatures, and power.",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        )
        subtitle.pack(anchor="w", pady=(2, 10))

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.pack(fill="x")

        self.pause_btn = ctk.CTkButton(
            controls,
            text="Pause",
            width=110,
            fg_color=ACCENT,
            hover_color=ACCENT_DEEP,
            command=self._toggle_pause,
        )
        self.pause_btn.pack(side="left")

        self.status = ctk.CTkLabel(controls, text="Starting…", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.status.pack(side="left", padx=14)

        self.cpu_meter = MeterRow(self, "CPU usage")
        self.cpu_meter.pack(fill="x", padx=20, pady=(4, 2))
        self.mem_meter = MeterRow(self, "Memory usage")
        self.mem_meter.pack(fill="x", padx=20, pady=(2, 8))

    def _build_body(self) -> None:
        container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=12, pady=(0, 16))
        container.grid_columnconfigure((0, 1), weight=1, uniform="cols")

        self.sec_system = Section(container, "System")
        self.sec_system.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.sec_cpu = Section(container, "CPU / Cores")
        self.sec_cpu.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

        self.sec_mem = Section(container, "Memory & Swap")
        self.sec_mem.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        self.sec_disk = Section(container, "Disks & I/O")
        self.sec_disk.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)

        self.sec_gpu = Section(container, "GPU / CUDA")
        self.sec_gpu.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        self.sec_power = Section(container, "PSU / Power")
        self.sec_power.grid(row=2, column=1, sticky="nsew", padx=8, pady=8)

        self.sec_net = Section(container, "Network")
        self.sec_net.grid(row=3, column=0, sticky="nsew", padx=8, pady=8)
        self.sec_temp = Section(container, "Temperatures")
        self.sec_temp.grid(row=3, column=1, sticky="nsew", padx=8, pady=8)

        self.sec_proc = Section(container, "Top processes")
        self.sec_proc.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=8, pady=8)

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.configure(text="Resume" if self._paused else "Pause")

    def _collect_loop(self) -> None:
        while self._running:
            if not self._paused:
                try:
                    snap = self.collector.collect()
                    with self._lock:
                        self._latest = snap
                except Exception as exc:  # noqa: BLE001 - surface in UI
                    with self._lock:
                        self._latest = None
                    self._error = str(exc)
            time.sleep(self.refresh_ms / 1000.0)

    def _ui_tick(self) -> None:
        with self._lock:
            snap = self._latest
        if snap is not None:
            self._render(snap)
        elif getattr(self, "_error", None):
            self.status.configure(text=f"Collector error: {self._error}")
        if self._running:
            self.after(250, self._ui_tick)

    def _render(self, snap: Snapshot) -> None:
        stamp = datetime.fromtimestamp(snap.collected_at).strftime("%H:%M:%S")
        state = "Paused" if self._paused else "Live"
        self.status.configure(text=f"{state} · updated {stamp}")

        self.cpu_meter.update_meter(
            snap.cpu.get("usage_percent"),
            f"{snap.cpu.get('usage_percent', 0):.1f}%",
        )
        self.mem_meter.update_meter(
            snap.memory.get("percent"),
            f"{snap.memory.get('used')} / {snap.memory.get('total')} ({snap.memory.get('percent')}%)",
        )

        sys = snap.system
        self.sec_system.set_text(
            "\n".join(
                [
                    f"Hostname     {sys.get('hostname')}",
                    f"OS           {sys.get('os')}",
                    f"Kernel       {sys.get('release')} ({sys.get('arch')})",
                    f"Uptime       {_fmt_uptime(sys.get('uptime_sec', 0))}",
                    f"Python       {sys.get('python')}",
                ]
            )
        )

        cores = snap.cpu.get("per_core_percent") or []
        core_lines = []
        for i, pct in enumerate(cores):
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            core_lines.append(f"Core {i:02d}  {bar}  {pct:5.1f}%")
        load = snap.cpu.get("load_avg") or []
        load_txt = " / ".join(f"{x:.2f}" for x in load) if load else "n/a"
        self.sec_cpu.set_text(
            "\n".join(
                [
                    f"Model        {snap.cpu.get('model')}",
                    f"Cores        {snap.cpu.get('physical_cores')} physical · {snap.cpu.get('logical_cores')} logical",
                    f"Frequency    {snap.cpu.get('freq_current_mhz') or 'n/a'} MHz (max {snap.cpu.get('freq_max_mhz') or 'n/a'})",
                    f"Load avg     {load_txt}",
                    "",
                    *core_lines,
                ]
            )
        )

        self.sec_mem.set_text(
            "\n".join(
                [
                    f"RAM used     {snap.memory.get('used')} / {snap.memory.get('total')} ({snap.memory.get('percent')}%)",
                    f"Available    {snap.memory.get('available')}",
                    f"Swap used    {snap.swap.get('used')} / {snap.swap.get('total')} ({snap.swap.get('percent')}%)",
                ]
            )
        )

        disk_lines = []
        for d in snap.disks:
            disk_lines.append(
                f"{d['mount']}  {d['used']} / {d['total']} ({d['percent']}%)  [{d['fstype']}]"
            )
        io = snap.disk_io or {}
        disk_lines.extend(
            [
                "",
                f"Read         {io.get('read_human_s', 'n/a')}",
                f"Write        {io.get('write_human_s', 'n/a')}",
            ]
        )
        self.sec_disk.set_text("\n".join(disk_lines) if disk_lines else "No disks found")

        if snap.gpu:
            gpu_lines = []
            for g in snap.gpu:
                gpu_lines.append(f"{g.get('vendor', '?')}: {g.get('name')}")
                if g.get("cuda_available"):
                    gpu_lines.extend(
                        [
                            f"  Driver     {g.get('driver')}",
                            f"  VRAM       {g.get('memory_used_mb')} / {g.get('memory_total_mb')} MB",
                            f"  GPU util   {g.get('util_gpu_percent')}% · mem util {g.get('util_mem_percent')}%",
                            f"  Temp       {g.get('temp_c')} °C",
                            f"  Power      {g.get('power_draw_w')} W / {g.get('power_limit_w')} W",
                            f"  Clocks     SM {g.get('clock_sm_mhz')} · MEM {g.get('clock_mem_mhz')} MHz",
                        ]
                    )
                elif g.get("note"):
                    gpu_lines.append(f"  {g['note']}")
            cuda = snap.cuda or {}
            gpu_lines.extend(
                [
                    "",
                    f"CUDA toolkit {'detected — ' + str(cuda.get('nvcc_version')) if cuda.get('toolkit_detected') else 'not detected'}",
                ]
            )
            if cuda.get("note") and not cuda.get("toolkit_detected"):
                gpu_lines.append(cuda["note"])
            self.sec_gpu.set_text("\n".join(gpu_lines))
        else:
            note = (snap.cuda or {}).get("note") or "No GPU devices detected."
            self.sec_gpu.set_text(note)

        power_lines = []
        for p in snap.power:
            power_lines.append(f"{p.get('name')}  ({p.get('type', p.get('status', 'power'))})")
            for key in ("status", "capacity", "voltage_v", "current_a", "power_w", "online", "detail", "manufacturer", "model_name"):
                if key in p and p[key] not in (None, ""):
                    power_lines.append(f"  {key}: {p[key]}")
        self.sec_power.set_text("\n".join(power_lines) if power_lines else "Power data unavailable")

        net_lines = []
        io = snap.net_io or {}
        net_lines.append(f"Throughput   ↓ {io.get('recv_human_s', 'n/a')}  ↑ {io.get('sent_human_s', 'n/a')}")
        net_lines.append("")
        for n in snap.network[:12]:
            up = "up" if n.get("isup") else "down"
            net_lines.append(f"{n['name']} [{n['family']}] {n['address']} ({up})")
        self.sec_net.set_text("\n".join(net_lines))

        if snap.temperatures:
            temp_lines = [f"{t['label']}: {t['current_c']:.1f} °C" for t in snap.temperatures[:16]]
            self.sec_temp.set_text("\n".join(temp_lines))
        else:
            self.sec_temp.set_text("No temperature sensors exposed on this host.")

        proc_lines = ["PID     CPU%   MEM%   NAME", "-" * 48]
        for p in snap.processes_top:
            proc_lines.append(
                f"{str(p['pid']):<7} {p['cpu_percent']:>5.1f}  {p['memory_percent']:>5.1f}  {p['name']}"
            )
        self.sec_proc.set_text("\n".join(proc_lines))

    def _on_close(self) -> None:
        self._running = False
        self.destroy()


def run_app() -> None:
    app = SpecForgeApp()
    app.mainloop()
