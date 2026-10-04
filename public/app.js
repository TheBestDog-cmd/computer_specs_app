const statusEl = document.getElementById("status");
const dashboardEl = document.getElementById("dashboard");
const refreshBtn = document.getElementById("refresh-btn");

function formatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  const parts = [];
  if (days) parts.push(`${days}d`);
  if (hours || days) parts.push(`${hours}h`);
  if (mins || hours || days) parts.push(`${mins}m`);
  parts.push(`${secs}s`);
  return parts.join(" ");
}

function fillList(elementId, rows) {
  const el = document.getElementById(elementId);
  el.innerHTML = rows
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(
      ([label, value]) => `
      <div class="row">
        <dt>${label}</dt>
        <dd>${value}</dd>
      </div>`
    )
    .join("");
}

function renderSpecs(specs) {
  fillList("system-list", [
    ["Hostname", specs.system.hostname],
    ["OS", specs.system.osPrettyName || `${specs.system.type} ${specs.system.release}`],
    ["Platform", `${specs.system.platform} / ${specs.system.arch}`],
    ["Uptime", formatUptime(specs.system.uptimeSec)],
  ]);

  fillList("cpu-list", [
    ["Model", specs.cpu.model],
    ["Cores", String(specs.cpu.cores)],
    ["Speed", specs.cpu.speedMHz ? `${specs.cpu.speedMHz} MHz` : "n/a"],
    [
      "Load",
      `${specs.cpu.load.one.toFixed(2)} / ${specs.cpu.load.five.toFixed(2)} / ${specs.cpu.load.fifteen.toFixed(2)}`,
    ],
  ]);

  fillList("memory-list", [
    ["Total", specs.memory.total],
    ["Used", `${specs.memory.used} (${specs.memory.usedPercent}%)`],
    ["Free", specs.memory.free],
  ]);
  document.getElementById("memory-bar").style.width = `${Math.min(specs.memory.usedPercent, 100)}%`;

  if (specs.disk) {
    fillList("disk-list", [
      ["Mount", specs.disk.mount],
      ["Filesystem", specs.disk.filesystem],
      ["Total", specs.disk.total],
      ["Used", `${specs.disk.used} (${specs.disk.usedPercent}%)`],
      ["Free", specs.disk.free],
    ]);
    document.getElementById("disk-bar").style.width = `${Math.min(specs.disk.usedPercent, 100)}%`;
  } else {
    fillList("disk-list", [["Status", "Unavailable on this host"]]);
    document.getElementById("disk-bar").style.width = "0%";
  }

  const networkEl = document.getElementById("network-list");
  if (!specs.network.length) {
    networkEl.innerHTML = `<p class="status">No external interfaces found.</p>`;
  } else {
    networkEl.innerHTML = specs.network
      .map(
        (iface) => `
        <article class="network-item">
          <strong>${iface.name} · ${iface.family}</strong>
          <span>${iface.address}${iface.cidr ? ` (${iface.cidr})` : ""}</span>
          <span>MAC ${iface.mac}</span>
        </article>`
      )
      .join("");
  }

  fillList("runtime-list", [
    ["Node", specs.runtime.node],
    ["PID", String(specs.runtime.pid)],
    ["CWD", specs.runtime.cwd],
    ["Collected", new Date(specs.collectedAt).toLocaleString()],
  ]);

  dashboardEl.hidden = false;
}

async function loadSpecs() {
  statusEl.textContent = "Fetching live specs…";
  refreshBtn.disabled = true;
  try {
    const response = await fetch("/api/specs", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const specs = await response.json();
    renderSpecs(specs);
    statusEl.textContent = `Updated ${new Date(specs.collectedAt).toLocaleTimeString()}`;
  } catch (error) {
    statusEl.textContent = `Failed to load specs: ${error.message}`;
  } finally {
    refreshBtn.disabled = false;
  }
}

refreshBtn.addEventListener("click", () => {
  loadSpecs();
});

loadSpecs();
setInterval(loadSpecs, 15000);
