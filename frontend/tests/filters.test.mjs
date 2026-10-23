import test from "node:test";
import assert from "node:assert/strict";
import {
  parseFilters,
  compactFilters,
  DEFAULT_FILTERS,
} from "../src/lib/filters-model.ts";

test("filter URLs round-trip selected constraints without dropping false or zero", () => {
  const filters = parseFilters({
    genders: ["unisex"],
    seasons: ["spring", "summer"],
    min_season_share: 0,
    min_rating: 4.2,
    include_notes: ["cedar", "cedar"],
    include_clones: false,
    budget_max: 35,
  });
  const url = new URL("http://localhost:3000/?unrelated=keep#collection");
  url.searchParams.set("filters", JSON.stringify(compactFilters(filters)));
  assert.deepEqual(
    parseFilters(JSON.parse(url.searchParams.get("filters"))),
    filters,
  );
  assert.deepEqual(filters.include_notes, ["cedar"]);
  assert.equal(url.hash, "#collection");
  assert.equal(url.searchParams.get("unrelated"), "keep");
  assert.deepEqual(compactFilters(DEFAULT_FILTERS), {});
});
test("untrusted filter URLs reject unknown keys, invalid numbers and contradictory criteria", () => {
  for (const value of [
    { toString: null },
    JSON.parse('{"__proto__":{}}'),
    { min_rating: 6 },
    { min_rating: "4" },
    { min_votes: 1.5 },
    { budget_max: 0 },
    { price_min: 70, price_max: 30 },
    { min_longevity: 4, max_longevity: 2 },
    { include_notes: ["oud"], exclude_notes: ["oud"] },
    { genders: ["everyone"] },
    { seasons: ["monsoon"] },
    { include_clones: "true" },
    { store: "jomashop" },
    { min_rating: Infinity },
  ])
    assert.throws(() => parseFilters(value));
});
test("multi-selects cannot introduce nested values or unbounded URL lists", () => {
  assert.throws(() => parseFilters({ include_notes: [{}] }));
  assert.throws(() =>
    parseFilters({
      include_notes: Array.from({ length: 101 }, (_, i) => `note ${i}`),
    }),
  );
});
