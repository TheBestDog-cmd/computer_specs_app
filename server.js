import express from "express";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { collectSpecs } from "./lib/specs.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOST || "0.0.0.0";

const app = express();

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, service: "computer-specs-app", uptimeSec: Math.floor(process.uptime()) });
});

app.get("/api/specs", (_req, res) => {
  res.json(collectSpecs());
});

app.use(express.static(path.join(__dirname, "public")));

app.use((_req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

const server = app.listen(PORT, HOST, () => {
  console.log(`computer_specs_app listening on http://${HOST}:${PORT}`);
  console.log(`hostname=${os.hostname()} platform=${process.platform} arch=${process.arch}`);
});

function shutdown(signal) {
  console.log(`Received ${signal}, shutting down`);
  server.close(() => process.exit(0));
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
