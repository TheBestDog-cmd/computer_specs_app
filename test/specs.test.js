import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { collectSpecs } from "../lib/specs.js";

describe("collectSpecs", () => {
  it("returns core system, cpu, and memory fields", () => {
    const specs = collectSpecs();
    assert.equal(typeof specs.system.hostname, "string");
    assert.ok(specs.system.hostname.length > 0);
    assert.equal(typeof specs.cpu.model, "string");
    assert.ok(specs.cpu.cores >= 1);
    assert.ok(specs.memory.totalBytes > 0);
    assert.equal(typeof specs.runtime.node, "string");
  });
});
