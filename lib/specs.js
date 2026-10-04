import os from "node:os";
import fs from "node:fs";
import { execSync } from "node:child_process";

function bytesToHuman(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "unknown";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 2)} ${units[unit]}`;
}

function cpuModel() {
  const cpus = os.cpus();
  return cpus[0]?.model?.trim() || "unknown";
}

function loadAverages() {
  const [one, five, fifteen] = os.loadavg();
  return { one, five, fifteen };
}

function memoryInfo() {
  const total = os.totalmem();
  const free = os.freemem();
  const used = total - free;
  return {
    totalBytes: total,
    freeBytes: free,
    usedBytes: used,
    total: bytesToHuman(total),
    free: bytesToHuman(free),
    used: bytesToHuman(used),
    usedPercent: total ? Number(((used / total) * 100).toFixed(1)) : 0,
  };
}

function diskInfo() {
  try {
    const output = execSync("df -k -P /", { encoding: "utf8" }).trim().split("\n");
    const parts = output[1]?.split(/\s+/) || [];
    if (parts.length < 6) return null;
    const totalKb = Number(parts[1]);
    const usedKb = Number(parts[2]);
    const availKb = Number(parts[3]);
    return {
      filesystem: parts[0],
      mount: parts[5],
      totalBytes: totalKb * 1024,
      usedBytes: usedKb * 1024,
      freeBytes: availKb * 1024,
      total: bytesToHuman(totalKb * 1024),
      used: bytesToHuman(usedKb * 1024),
      free: bytesToHuman(availKb * 1024),
      usedPercent: Number(String(parts[4]).replace("%", "")),
    };
  } catch {
    return null;
  }
}

function networkInterfaces() {
  const nets = os.networkInterfaces();
  const result = [];
  for (const [name, entries] of Object.entries(nets)) {
    for (const entry of entries || []) {
      if (entry.internal) continue;
      result.push({
        name,
        family: entry.family,
        address: entry.address,
        mac: entry.mac,
        cidr: entry.cidr,
      });
    }
  }
  return result;
}

function prettyOsName() {
  try {
    const data = Object.fromEntries(
      fs
        .readFileSync("/etc/os-release", "utf8")
        .split("\n")
        .filter((line) => line.includes("="))
        .map((line) => {
          const idx = line.indexOf("=");
          const key = line.slice(0, idx);
          const value = line.slice(idx + 1).replace(/^"|"$/g, "");
          return [key, value];
        })
    );
    return data.PRETTY_NAME || null;
  } catch {
    return null;
  }
}

export function collectSpecs() {
  const cpus = os.cpus();
  return {
    collectedAt: new Date().toISOString(),
    system: {
      hostname: os.hostname(),
      platform: process.platform,
      arch: process.arch,
      release: os.release(),
      type: os.type(),
      uptimeSec: Math.floor(os.uptime()),
      osPrettyName: prettyOsName(),
      homeDir: os.homedir(),
      tmpDir: os.tmpdir(),
    },
    cpu: {
      model: cpuModel(),
      cores: cpus.length,
      speedMHz: cpus[0]?.speed || null,
      load: loadAverages(),
    },
    memory: memoryInfo(),
    disk: diskInfo(),
    network: networkInterfaces(),
    runtime: {
      node: process.version,
      pid: process.pid,
      cwd: process.cwd(),
      execPath: process.execPath,
    },
  };
}
