import test from "node:test";
import assert from "node:assert/strict";
import {
  browserOrigin,
  validMutationOrigin,
  returnLocation,
} from "../src/lib/proxy-policy.ts";
test("local OAuth return follows the browser host rather than Next's internal localhost URL", () => {
  assert.equal(
    browserOrigin(
      "http://localhost:3002/api/account/auth/google/callback",
      "127.0.0.1:3002",
    ),
    "http://127.0.0.1:3002",
  );
  assert.equal(
    returnLocation(
      "http://127.0.0.1:3002/?signed_in=1",
      "http://localhost:3002/callback",
      "127.0.0.1:3002",
    ),
    "http://127.0.0.1:3002/?signed_in=1",
  );
});
test("production HTTPS origin is pinned even when the internal server speaks HTTP", () => {
  const args = [
    "http://internal:8080/api/account/me",
    "internal:8080",
    "https://scent.example",
  ];
  assert.equal(validMutationOrigin("https://scent.example", ...args), true);
  for (const origin of [
    null,
    "null",
    "https://attacker.example",
    "https://scent.example/path",
    "https://user@scent.example",
  ])
    assert.equal(validMutationOrigin(origin, ...args), false);
  assert.equal(returnLocation("https://attacker.example", ...args), null);
  assert.equal(returnLocation("https://user@scent.example/", ...args), null);
  assert.equal(
    returnLocation("/?google_connected=1", ...args),
    "https://scent.example/?google_connected=1",
  );
});
