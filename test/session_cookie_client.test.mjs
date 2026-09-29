import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../backend/session_cookie.js", import.meta.url), "utf8");
const { default: syncCookie } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

function browser({ blocked = false, cookie = "", protocol = "http:" } = {}) {
  let jar = cookie;
  const writes = [], reports = [];
  globalThis.window = { location: { protocol } };
  globalThis.document = {
    get cookie() { return jar; },
    set cookie(value) {
      writes.push(value);
      if (!blocked) jar = value.includes("Max-Age=0;") ? "" : value.split(";")[0];
    },
  };
  const run = (value, reported) => syncCookie({
    data: { name: "sc_token", value, maxAge: value ? 315360000 : 0, reported },
    setStateValue: (name, status) => reports.push({ name, status }),
  });
  return { run, writes, reports, read: () => jar };
}

test("writes a persistent same-site cookie and acknowledges it once", () => {
  const client = browser();
  client.run("opaque-token");
  assert.equal(client.read(), "sc_token=opaque-token");
  assert.match(client.writes[0], /Max-Age=315360000; Path=\/; SameSite=Lax/);
  assert.deepEqual(client.reports, [{ name: "status", status: "saved" }]);
  client.run("opaque-token", "saved");
  assert.equal(client.writes.length, 1);
  assert.equal(client.reports.length, 1);
  assert.deepEqual(window.location, { protocol: "http:" });
});

test("adds Secure when served over HTTPS", () => {
  const client = browser({ protocol: "https:" });
  client.run("opaque-token");
  assert.match(client.writes[0], /; Secure$/);
});

test("logout clears the cookie, including across acknowledgement reruns", () => {
  const client = browser({ cookie: "other=value; sc_token=old-token" });
  client.run("");
  assert.equal(client.read(), "");
  assert.match(client.writes[0], /sc_token=; Max-Age=0;/);
  client.run("", "saved");
  assert.equal(client.writes.length, 1);
});

test("blocked cookies report failure without an acknowledgement loop", () => {
  const client = browser({ blocked: true });
  client.run("opaque-token");
  assert.deepEqual(client.reports, [{ name: "status", status: "blocked" }]);
  client.run("opaque-token", "blocked");
  assert.equal(client.reports.length, 1);
});
