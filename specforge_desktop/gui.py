"""CustomTkinter GUI for real-time SpecForge monitoring."""

from __future__ import annotations

import threading
import time
from datetime import datetime

import customtkinter as ctk

from specforge_desktop import __version__
from specforge_desktop.collector import SpecsCollector, Snapshot
from specforge_desktop import updater


ACCENT = "#0F7A6B"
ACCENT_DEEP = "#0B5348"
INK = "#122027"
MUTED = "#4D646E"
PANEL = "#F4F8F6"
TRACK = "#D7E3DE"
WARN = "#C46B2C"

# Pause every snapshot-driven widget update after scroll/drag so the UI thread
# can paint wheel/scrollbar motion without competing CTk configure/layout work.
SCROLL_PAUSE_SEC = 0.55


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


def format_core_lines(cores: list[float], expected: int | None = None, *, dense_after: int = 16) -> list[str]:
    """Render per-core bars; collapse very high core counts to keep redraws cheap."""
    n = len(cores)
    exp = expected if expected is not None else n
    lines: list[str] = []

    def one(i: int, pct: float) -> str:
        filled = min(10, max(0, int(pct // 10)))
        bar = "#" * filled + "-" * (10 - filled)
        return f"Core {i:02d}  [{bar}]  {pct:5.1f}%"

    if n <= dense_after:
        lines.extend(one(i, pct) for i, pct in enumerate(cores))
    elif n:
        # Compact summary + endpoints so large CPUs do not thrash the textbox.
        avg = sum(cores) / n
        mn = min(cores)
        mx = max(cores)
        lines.append(f"Cores       {n} logical  avg {avg:5.1f}%  min {mn:5.1f}%  max {mx:5.1f}%")
        lines.append("")
        show = 4
        for i in range(show):
            lines.append(one(i, cores[i]))
        lines.append(f"… ({n - show * 2} cores omitted while monitoring) …")
        for i in range(n - show, n):
            lines.append(one(i, cores[i]))

    if exp and n < exp:
        lines.append(
            f"… only {n} of {exp} logical cores reported "
            "(process may be affinity-limited or 32-bit)"
        )
    return lines


def format_system_lines(snap: Snapshot) -> list[str]:
    sys = snap.system or {}
    return [
        f"Hostname     {sys.get('hostname')}",
        f"OS           {sys.get('os')}",
        f"Kernel       {sys.get('release')} ({sys.get('arch')})",
        f"Uptime       {_fmt_uptime(sys.get('uptime_sec', 0))}",
        f"Python       {sys.get('python')}",
    ]


def format_temperature_lines(snap: Snapshot, *, include_heading: bool = True) -> list[str]:
    """Format every collected temperature sensor for the Temperatures panel/section."""
    status = snap.temperature_status or {}
    cpu_ok = isinstance(status.get("cpu_c"), (int, float))
    gpu_ok = isinstance(status.get("gpu_c"), (int, float))
    lines: list[str] = []
    if include_heading:
        lines.append("=== Temperatures ===")
    lines.extend(
        [
            f"CPU temp     {status['cpu_c']:.1f} C" if cpu_ok else "CPU temp     unavailable",
            f"GPU temp     {status['gpu_c']:.1f} C" if gpu_ok else "GPU temp     unavailable",
        ]
    )
    sources = status.get("sources") or []
    if sources:
        lines.append(f"Sources      {', '.join(str(s) for s in sources)}")

    rows = list(snap.temperatures or [])
    if rows:
        kind_titles = {
            "cpu": "CPU",
            "gpu": "GPU",
            "acpi": "Board / ACPI",
            "other": "Other sensors",
        }
        kind_order = ("cpu", "gpu", "acpi", "other")
        grouped: dict[str, list[dict]] = {k: [] for k in kind_order}
        for row in rows:
            kind = str(row.get("kind") or "other")
            if kind not in grouped:
                kind = "other"
            grouped[kind].append(row)

        for kind in kind_order:
            group = grouped[kind]
            if not group:
                continue
            lines.append("")
            lines.append(f"-- {kind_titles[kind]} --")
            for t in group:
                label = str(t.get("label") or t.get("sensor") or "Sensor")
                src = t.get("source") or t.get("sensor") or "?"
                current = t.get("current_c")
                if not isinstance(current, (int, float)):
                    continue
                extra = ""
                high = t.get("high_c")
                critical = t.get("critical_c")
                if isinstance(high, (int, float)):
                    extra += f"  high {high:.0f}"
                if isinstance(critical, (int, float)):
                    extra += f"  crit {critical:.0f}"
                lines.append(f"  {label:<28} {current:5.1f} C  [{src}]{extra}")
    else:
        lines.append("")
        lines.append("No live sensor readings yet.")

    notes = [str(n).strip() for n in (status.get("notes") or []) if str(n).strip()]
    # Always surface enablement guidance when CPU/GPU temps are missing — never leave
    # the panel with only a bare "unavailable" line and no next step.
    if not notes and (not cpu_ok or not gpu_ok or not rows):
        if not cpu_ok:
            notes.append(
                "CPU: on Windows run LibreHardwareMonitor (Admin); on Linux install lm-sensors / check hwmon."
            )
        if not gpu_ok:
            notes.append(
                "GPU: install NVIDIA drivers so nvidia-smi works, or use amd-smi / LibreHardwareMonitor for AMD."
            )
        if not rows and cpu_ok and gpu_ok:
            notes.append("Sensor list is empty even though summary temps exist; refresh or restart SpecForge.")
    if notes:
        lines.append("")
        lines.append("How to enable missing temps:")
        for note in notes:
            lines.append(f"- {note}")
    return lines


def build_dashboard_text(
    snap: Snapshot,
    *,
    include_system: bool = True,
    include_temperatures: bool = True,
) -> str:
    """Build the scrollable dashboard body (pure; safe to unit-test).

    When System / Temperatures live in their own top panels, pass
    include_system=False and include_temperatures=False so those blocks are omitted.
    """
    blocks: list[str] = []

    if include_system:
        blocks.append("\n".join(["=== System ===", *format_system_lines(snap)]))

    cores = snap.cpu.get("per_core_percent") or []
    logical = snap.cpu.get("logical_cores")
    try:
        expected = int(logical) if logical is not None else len(cores)
    except (TypeError, ValueError):
        expected = len(cores)
    load = snap.cpu.get("load_avg") or []
    load_txt = " / ".join(f"{x:.2f}" for x in load) if load else "n/a"
    cpu_temp = snap.cpu.get("temp_c")
    cpu_temp_txt = f"{cpu_temp:.1f} C" if isinstance(cpu_temp, (int, float)) else "unavailable"
    blocks.append(
        "\n".join(
            [
                "=== CPU / Cores ===",
                f"Model        {snap.cpu.get('model')}",
                f"Cores        {snap.cpu.get('physical_cores')} physical · {snap.cpu.get('logical_cores')} logical",
                f"Frequency    {snap.cpu.get('freq_current_mhz') or 'n/a'} MHz (max {snap.cpu.get('freq_max_mhz') or 'n/a'})",
                f"CPU temp     {cpu_temp_txt}",
                f"Load avg     {load_txt}",
                "",
                *format_core_lines(list(cores), expected),
            ]
        )
    )

    blocks.append(
        "\n".join(
            [
                "=== Memory & Swap ===",
                f"RAM used     {snap.memory.get('used')} / {snap.memory.get('total')} ({snap.memory.get('percent')}%)",
                f"Available    {snap.memory.get('available')}",
                f"Swap used    {snap.swap.get('used')} / {snap.swap.get('total')} ({snap.swap.get('percent')}%)",
            ]
        )
    )

    disk_lines = ["=== Disks & I/O ==="]
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
    blocks.append("\n".join(disk_lines) if len(disk_lines) > 1 else "=== Disks & I/O ===\nNo disks found")

    gpu_lines = ["=== GPU / CUDA ==="]
    if snap.gpu:
        for g in snap.gpu:
            gpu_lines.append(f"{g.get('vendor', '?')}: {g.get('name')}")
            temp = g.get("temp_c")
            temp_txt = f"{temp:.1f} C" if isinstance(temp, (int, float)) else "unavailable"
            if g.get("cuda_available") or g.get("vendor") == "NVIDIA":
                gpu_lines.extend(
                    [
                        f"  Temp       {temp_txt}",
                        f"  Driver     {g.get('driver')}",
                        f"  VRAM       {g.get('memory_used_mb')} / {g.get('memory_total_mb')} MB",
                        f"  GPU util   {g.get('util_gpu_percent')}% · mem util {g.get('util_mem_percent')}%",
                        f"  Power      {g.get('power_draw_w')} W / {g.get('power_limit_w')} W",
                        f"  Clocks     SM {g.get('clock_sm_mhz')} · MEM {g.get('clock_mem_mhz')} MHz",
                    ]
                )
            else:
                gpu_lines.append(f"  Temp       {temp_txt}")
                if g.get("note"):
                    gpu_lines.append(f"  {g['note']}")
        cuda = snap.cuda or {}
        gpu_lines.extend(
            [
                "",
                f"CUDA toolkit {'detected - ' + str(cuda.get('nvcc_version')) if cuda.get('toolkit_detected') else 'not detected'}",
            ]
        )
        if cuda.get("note") and not cuda.get("toolkit_detected"):
            gpu_lines.append(cuda["note"])
    else:
        note = (snap.cuda or {}).get("note") or "No GPU devices detected."
        gpu_lines.append(note)
    blocks.append("\n".join(gpu_lines))

    if include_temperatures:
        blocks.append("\n".join(format_temperature_lines(snap)))

    net_lines = ["=== Network ==="]
    io = snap.net_io or {}
    net_lines.append(f"Throughput   down {io.get('recv_human_s', 'n/a')}  up {io.get('sent_human_s', 'n/a')}")
    net_lines.append("")
    for n in snap.network[:12]:
        up = "up" if n.get("isup") else "down"
        net_lines.append(f"{n['name']} [{n['family']}] {n['address']} ({up})")
    blocks.append("\n".join(net_lines))

    proc_lines = ["=== Top processes ===", "PID     CPU%   MEM%   NAME", "-" * 48]
    for p in snap.processes_top:
        proc_lines.append(
            f"{str(p['pid']):<7} {p['cpu_percent']:>5.1f}  {p['memory_percent']:>5.1f}  {p['name']}"
        )
    blocks.append("\n".join(proc_lines))

    return "\n\n".join(blocks)


class MeterRow(ctk.CTkFrame):
    def __init__(self, master, title: str, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self._last_label = None
        self._last_pct = None
        self.title = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT_DEEP)
        self.title.grid(row=0, column=0, columnspan=2, sticky="w")
        self.value = ctk.CTkLabel(self, text="—", font=ctk.CTkFont(family="Consolas", size=12), text_color=MUTED)
        self.value.grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.bar = ctk.CTkProgressBar(self, height=10, progress_color=ACCENT, fg_color=TRACK)
        self.bar.grid(row=1, column=1, sticky="ew")
        self.bar.set(0)

    def update_meter(self, percent: float | None, label: str) -> None:
        pct = 0.0 if percent is None else max(0.0, min(float(percent), 100.0))
        # Avoid redundant widget updates (major source of scroll jank).
        if label == self._last_label and self._last_pct is not None and abs(pct - self._last_pct) < 0.2:
            return
        self._last_label = label
        self._last_pct = pct
        self.bar.set(pct / 100.0)
        self.bar.configure(progress_color=WARN if pct >= 85 else ACCENT)
        self.value.configure(text=label)



class Section(ctk.CTkFrame):
    """Small titled panel used for the System / Temperatures top row."""

    def __init__(self, master, title: str, *, scrollable: bool = False, **kwargs):
        super().__init__(master, fg_color=PANEL, corner_radius=10, border_width=1, border_color="#D5E0DB", **kwargs)
        self._last_text = None
        self.title = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=15, weight="bold"), text_color=ACCENT_DEEP)
        self.title.pack(anchor="w", padx=14, pady=(12, 4))
        self.body = ctk.CTkTextbox(
            self,
            height=120,
            activate_scrollbars=scrollable,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=INK,
            fg_color=PANEL,
            border_width=0,
            wrap="word",
        )
        self.body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.body.insert("1.0", "Loading…")
        self.body.configure(state="disabled")

    def set_height(self, px: int) -> None:
        self.body.configure(height=px)

    def set_text(self, text: str) -> None:
        if text == self._last_text:
            return
        self._last_text = text
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.body.insert("1.0", text)
        self.body.configure(state="disabled")


class SpecForgeApp(ctk.CTk):
    def __init__(self, refresh_ms: int = 1000):
        super().__init__()
        self.refresh_ms = refresh_ms
        self.collector = SpecsCollector()
        self._lock = threading.Lock()
        self._latest: Snapshot | None = None
        self._dirty = False
        self._running = True
        self._paused = False
        self._error: str | None = None
        self._last_rendered_at: float | None = None
        self._scroll_until = 0.0
        self._last_dashboard = None
        self._last_system = None
        self._last_temp = None
        self._last_status = None
        self._scroll_hint_shown = False

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")

        self.title("SpecForge — Real-time Computer Specs")
        self.geometry("1180x820")
        self.minsize(960, 700)
        self.configure(fg_color="#E8F0EC")

        self._build_header()
        self._build_body()
        self._bind_scroll_pause()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._worker = threading.Thread(target=self._collect_loop, daemon=True)
        self._worker.start()
        self.after(150, self._ui_tick)

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
            text="Live inventory and usage for CPU, memory, disks, network, GPU/CUDA, temperatures, and top processes.",
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

        self.updates_btn = ctk.CTkButton(
            controls,
            text="Updates",
            width=110,
            fg_color="#2F5D62",
            hover_color=ACCENT_DEEP,
            command=self._open_updates,
        )
        self.updates_btn.pack(side="left", padx=(10, 0))

        self.web_btn = ctk.CTkButton(
            controls,
            text="GitHub",
            width=90,
            fg_color="#3D6B74",
            hover_color=ACCENT_DEEP,
            command=lambda: updater.open_github(),
        )
        self.web_btn.pack(side="left", padx=(10, 0))

        self.status = ctk.CTkLabel(controls, text="Starting…", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.status.pack(side="left", padx=14)

        self.cpu_meter = MeterRow(self, "CPU usage")
        self.cpu_meter.pack(fill="x", padx=20, pady=(4, 2))
        self.mem_meter = MeterRow(self, "Memory usage")
        self.mem_meter.pack(fill="x", padx=20, pady=(2, 2))

        temps = ctk.CTkFrame(self, fg_color="transparent")
        temps.pack(fill="x", padx=20, pady=(2, 8))
        temps.grid_columnconfigure((0, 1), weight=1, uniform="temps")
        self.cpu_temp_meter = MeterRow(temps, "CPU temperature")
        self.cpu_temp_meter.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.gpu_temp_meter = MeterRow(temps, "GPU temperature")
        self.gpu_temp_meter.grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def _build_body(self) -> None:
        # Top row: System | Temperatures. Everything else is pushed into the
        # scrollable dashboard below (one native textbox keeps scrolling smooth).
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(0, 8))
        top.grid_columnconfigure((0, 1), weight=1, uniform="top")

        self.sec_system = Section(top, "System")
        self.sec_system.set_height(110)
        self.sec_system.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.sec_temp = Section(top, "Temperatures", scrollable=True)
        self.sec_temp.set_height(160)
        self.sec_temp.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        shell = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10, border_width=1, border_color="#D5E0DB")
        shell.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        title = ctk.CTkLabel(
            shell,
            text="Live dashboard",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=ACCENT_DEEP,
        )
        title.pack(anchor="w", padx=14, pady=(12, 4))

        self.dashboard = ctk.CTkTextbox(
            shell,
            activate_scrollbars=True,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=INK,
            fg_color=PANEL,
            border_width=0,
            wrap="none",
        )
        self.dashboard.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.dashboard.insert("1.0", "Loading…")
        self.dashboard.configure(state="disabled")

    def _mark_scroll(self, _event=None) -> None:
        self._scroll_until = time.monotonic() + SCROLL_PAUSE_SEC

    def _bind_scroll_pause(self) -> None:
        """Hard-pause ALL live widget updates while the user scrolls/drags."""
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(seq, self._mark_scroll, add="+")

        # CTkTextbox wraps a tk Text; bind wheel + scrollbar drag there too.
        targets = [self.dashboard, self.sec_temp.body, self.sec_system.body]
        for candidate in (self.dashboard, self.sec_temp.body, self.sec_system.body):
            try:
                targets.append(candidate._textbox)  # noqa: SLF001 - CTk internal
            except Exception:
                pass
        for widget in targets:
            try:
                widget.bind("<MouseWheel>", self._mark_scroll, add="+")
                widget.bind("<Button-4>", self._mark_scroll, add="+")
                widget.bind("<Button-5>", self._mark_scroll, add="+")
                widget.bind("<ButtonPress-1>", self._mark_scroll, add="+")
                widget.bind("<B1-Motion>", self._mark_scroll, add="+")
            except Exception:
                pass

    def _set_status(self, text: str) -> None:
        if text == self._last_status:
            return
        self._last_status = text
        self.status.configure(text=text)

    def _set_dashboard(self, text: str) -> None:
        if text == self._last_dashboard:
            return
        self._last_dashboard = text
        # Preserve scroll position across live refreshes so the view does not jump.
        try:
            yview = self.dashboard.yview()
        except Exception:
            yview = (0.0, 1.0)
        self.dashboard.configure(state="normal")
        self.dashboard.delete("1.0", "end")
        self.dashboard.insert("1.0", text)
        self.dashboard.configure(state="disabled")
        try:
            self.dashboard.yview_moveto(yview[0])
        except Exception:
            pass

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
                        self._dirty = True
                        self._error = None
                except Exception as exc:  # noqa: BLE001 - surface in UI
                    with self._lock:
                        self._latest = None
                        self._dirty = True
                        self._error = str(exc)
            time.sleep(self.refresh_ms / 1000.0)

    def _ui_tick(self) -> None:
        scrolling = time.monotonic() < self._scroll_until
        with self._lock:
            dirty = self._dirty
            snap = self._latest
            err = self._error
            if dirty and not scrolling:
                self._dirty = False

        if err and snap is None:
            self._set_status(f"Collector error: {err}")
        elif snap is not None:
            if scrolling:
                # Freeze meters + dashboard entirely; only a cheap status hint.
                if dirty:
                    with self._lock:
                        self._dirty = True
                if not self._scroll_hint_shown:
                    self._set_status("Live · updates paused while scrolling")
                    self._scroll_hint_shown = True
            else:
                self._scroll_hint_shown = False
                self._render_header(snap)
                if dirty and snap.collected_at != self._last_rendered_at:
                    self._render_dashboard(snap)
                    self._last_rendered_at = snap.collected_at

        if self._running:
            # ~10 FPS UI scheduler is enough; data itself arrives ~1 Hz.
            self.after(100, self._ui_tick)

    @staticmethod
    def _temp_meter_values(temp_c: float | None) -> tuple[float | None, str]:
        if temp_c is None:
            return None, "unavailable"
        # Map typical 30–95 C operating range onto the progress bar.
        pct = max(0.0, min(100.0, (float(temp_c) - 30.0) * (100.0 / 65.0)))
        return pct, f"{float(temp_c):.1f} C"

    def _render_header(self, snap: Snapshot) -> None:
        stamp = datetime.fromtimestamp(snap.collected_at).strftime("%H:%M:%S")
        state = "Paused" if self._paused else "Live"
        self._set_status(f"{state} · updated {stamp}")
        self.cpu_meter.update_meter(
            snap.cpu.get("usage_percent"),
            f"{snap.cpu.get('usage_percent', 0):.1f}%",
        )
        self.mem_meter.update_meter(
            snap.memory.get("percent"),
            f"{snap.memory.get('used')} / {snap.memory.get('total')} ({snap.memory.get('percent')}%)",
        )
        status = snap.temperature_status or {}
        cpu_temp = status.get("cpu_c", snap.cpu.get("temp_c"))
        gpu_temp = status.get("gpu_c")
        cpu_pct, cpu_label = self._temp_meter_values(cpu_temp)
        gpu_pct, gpu_label = self._temp_meter_values(gpu_temp)
        self.cpu_temp_meter.update_meter(cpu_pct, cpu_label)
        self.gpu_temp_meter.update_meter(gpu_pct, gpu_label)

    def _render_dashboard(self, snap: Snapshot) -> None:
        system_text = "\n".join(format_system_lines(snap))
        if system_text != self._last_system:
            self._last_system = system_text
            self.sec_system.set_text(system_text)

        temp_text = "\n".join(format_temperature_lines(snap, include_heading=False))
        if temp_text != self._last_temp:
            self._last_temp = temp_text
            self.sec_temp.set_text(temp_text)

        # System + Temperatures already occupy the top row; omit them here.
        self._set_dashboard(
            build_dashboard_text(snap, include_system=False, include_temperatures=False)
        )

    def _open_updates(self) -> None:
        UpdatesDialog(self)

    def _on_close(self) -> None:
        self._running = False
        self.destroy()


class UpdatesDialog(ctk.CTkToplevel):
    def __init__(self, master: SpecForgeApp):
        super().__init__(master)
        self.title("SpecForge Updates")
        self.geometry("560x420")
        self.resizable(False, False)
        self.configure(fg_color="#E8F0EC")
        self.transient(master)
        self.after(50, self.lift)
        self.after(80, self.focus_force)

        ctk.CTkLabel(
            self,
            text="GitHub updates",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=ACCENT_DEEP,
        ).pack(anchor="w", padx=20, pady=(18, 4))

        ctk.CTkLabel(
            self,
            text="Check the web repo, pull the latest main branch, or open GitHub in your browser.",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 12))

        self.info = ctk.CTkTextbox(self, height=180, font=ctk.CTkFont(family="Consolas", size=12))
        self.info.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self.info.insert("1.0", f"App version: {__version__}\nChecking GitHub…")
        self.info.configure(state="disabled")

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 18))

        self.check_btn = ctk.CTkButton(row, text="Check", width=100, fg_color=ACCENT, hover_color=ACCENT_DEEP, command=self._check)
        self.check_btn.pack(side="left")
        self.pull_btn = ctk.CTkButton(row, text="Update now", width=120, fg_color="#2F5D62", hover_color=ACCENT_DEEP, command=self._pull)
        self.pull_btn.pack(side="left", padx=8)
        self.pull_btn.configure(state="disabled")
        self.web_btn = ctk.CTkButton(row, text="Open GitHub", width=120, fg_color="#3D6B74", hover_color=ACCENT_DEEP, command=lambda: updater.open_github())
        self.web_btn.pack(side="left")
        self.releases_btn = ctk.CTkButton(row, text="Releases", width=100, fg_color="#3D6B74", hover_color=ACCENT_DEEP, command=updater.open_releases)
        self.releases_btn.pack(side="left", padx=8)

        self._latest_info: updater.UpdateInfo | None = None
        self.after(100, self._check)

    def _set_info(self, text: str) -> None:
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", text)
        self.info.configure(state="disabled")

    def _set_update_enabled(self, enabled: bool) -> None:
        self.pull_btn.configure(state="normal" if enabled else "disabled")

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.check_btn.configure(state=state)
        self.web_btn.configure(state=state)
        self.releases_btn.configure(state=state)
        if busy:
            self.pull_btn.configure(state="disabled")
        else:
            allowed = bool(self._latest_info and self._latest_info.update_available)
            self._set_update_enabled(allowed)

    def _check(self) -> None:
        self._busy(True)
        self._set_info(f"App version: {__version__}\nChecking GitHub…")

        def work():
            info_obj: updater.UpdateInfo | None = None
            try:
                info_obj = updater.check_for_updates(__version__)
                lines = [
                    f"App version     {info_obj.local_version}",
                    f"GitHub version  {info_obj.remote_version or 'unknown'}",
                    f"Install mode    {info_obj.mode}",
                    f"Local commit    {info_obj.local_commit or 'unknown'}",
                    f"GitHub commit   {info_obj.remote_commit or 'unknown'}",
                    f"Commit date     {info_obj.remote_date or 'n/a'}",
                    f"Commit message  {info_obj.remote_message or 'n/a'}",
                    f"Release tag     {info_obj.release_tag or 'none yet'}",
                    "",
                    ("UPDATE AVAILABLE" if info_obj.update_available else "UP TO DATE"),
                    info_obj.detail,
                    "",
                    "Update now is enabled only when a newer version is available.",
                    "Exe installs compare version.json from GitHub Releases;",
                    "git checkouts can also update when main has a newer commit.",
                ]
                msg = "\n".join(lines)
            except Exception as exc:  # noqa: BLE001
                msg = f"Could not check GitHub:\n{exc}"

            def finish():
                self._latest_info = info_obj
                self._done(msg)

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _done(self, msg: str) -> None:
        self._set_info(msg)
        self._busy(False)

    def _pull(self) -> None:
        if not (self._latest_info and self._latest_info.update_available):
            self._set_info(
                f"App version: {__version__}\n\n"
                "No newer version is available.\n"
                "Click Check again after a new SpecForge release is published."
            )
            self._set_update_enabled(False)
            return

        self._busy(True)
        self._set_info("Pulling latest from GitHub…")

        def work():
            try:
                result, should_restart = updater.apply_update(__version__)
                msg = result
                if should_restart:
                    msg += "\n\nClosing SpecForge so the new exe can start…"
                else:
                    msg += "\n\nRestart SpecForge to load code changes."
            except Exception as exc:  # noqa: BLE001
                should_restart = False
                msg = f"Update failed:\n{exc}"

            def finish():
                # Re-check so Update now stays disabled once we're current.
                try:
                    self._latest_info = updater.check_for_updates(__version__)
                except Exception:
                    self._latest_info = None
                self._done(msg)
                if should_restart:
                    # Give the UI a moment to show the message, then exit for the swap script.
                    self.after(1200, self._restart_for_exe_update)

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _restart_for_exe_update(self) -> None:
        # Hard-stop so Windows releases SpecForge.exe before the swap script copies.
        try:
            self.master._running = False  # noqa: SLF001 - stop collector loop
        except Exception:
            pass
        try:
            self.master.destroy()
        except Exception:
            pass
        import os

        os._exit(0)


def run_app() -> None:
    app = SpecForgeApp()
    app.mainloop()
