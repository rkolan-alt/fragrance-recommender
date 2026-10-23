export type Filters = {
  genders: string[];
  seasons: string[];
  min_season_share: number;
  min_rating: number | null;
  min_votes: number | null;
  min_longevity: number | null;
  max_longevity: number | null;
  include_accords: string[];
  exclude_accords: string[];
  include_notes: string[];
  exclude_notes: string[];
  exclude_brands: string[];
  include_clones: boolean;
  price_min: number | null;
  price_max: number | null;
  budget_max: number;
  store: "any" | "amazon";
};
export type SavedFilter = {
  id: string;
  name: string;
  filter_json: Partial<Filters>;
  is_default: boolean;
  is_custom_row: boolean;
};
export type FilterOptions = {
  accords: string[];
  notes: string[];
  brands: string[];
};
export const DEFAULT_FILTERS: Filters = {
  genders: [],
  seasons: [],
  min_season_share: 0.5,
  min_rating: null,
  min_votes: null,
  min_longevity: null,
  max_longevity: null,
  include_accords: [],
  exclude_accords: [],
  include_notes: [],
  exclude_notes: [],
  exclude_brands: [],
  include_clones: false,
  price_min: null,
  price_max: null,
  budget_max: 60,
  store: "any",
};

export function parseFilters(value: unknown): Filters {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid filters.");
  const result = { ...DEFAULT_FILTERS };
  for (const [key, item] of Object.entries(value)) {
    if (!Object.hasOwn(DEFAULT_FILTERS, key))
      throw new Error("Unknown filter.");
    const field = key as keyof Filters;
    const fallback = DEFAULT_FILTERS[field];
    if (Array.isArray(fallback)) {
      if (
        !Array.isArray(item) ||
        item.length > 100 ||
        item.some((v) => typeof v !== "string" || v.length > 200)
      )
        throw new Error("Invalid filter choices.");
      Object.assign(result, { [key]: [...new Set(item)] });
    } else if (field === "include_clones") {
      if (typeof item !== "boolean") throw new Error("Invalid clone filter.");
      result.include_clones = item;
    } else if (field === "store") {
      if (item !== "any" && item !== "amazon")
        throw new Error("Invalid store.");
      result.store = item;
    } else {
      if (
        (item === null && fallback !== null) ||
        (item !== null && (typeof item !== "number" || !Number.isFinite(item)))
      )
        throw new Error("Invalid numeric filter.");
      Object.assign(result, { [key]: item });
    }
  }
  if (
    result.genders.some((v) => !["male", "female", "unisex"].includes(v)) ||
    result.seasons.some(
      (v) => !["spring", "summer", "autumn", "winter"].includes(v),
    )
  )
    throw new Error("Invalid gender or season.");
  const ranges: [number | null, number, number][] = [
    [result.min_rating, 0, 5],
    [result.min_votes, 0, 1e9],
    [result.min_longevity, 1, 5],
    [result.max_longevity, 1, 5],
    [result.price_min, 0, 10000],
    [result.price_max, 0, 10000],
    [result.budget_max, 0.01, 10000],
    [result.min_season_share, 0, 1],
  ];
  if (
    ranges.some(([v, min, max]) => v !== null && (v < min || v > max)) ||
    (result.min_votes !== null && !Number.isInteger(result.min_votes))
  )
    throw new Error("A filter value is out of range.");
  if (
    result.price_min !== null &&
    result.price_max !== null &&
    result.price_min > result.price_max
  )
    throw new Error("Minimum price must not exceed maximum price.");
  if (
    result.min_longevity !== null &&
    result.max_longevity !== null &&
    result.min_longevity > result.max_longevity
  )
    throw new Error("Minimum longevity must not exceed maximum longevity.");
  for (const [included, excluded] of [
    [result.include_accords, result.exclude_accords],
    [result.include_notes, result.exclude_notes],
  ])
    if (included.some((v) => excluded.includes(v)))
      throw new Error("A scent cannot be both included and excluded.");
  return result;
}
export function compactFilters(filters: Filters) {
  return Object.fromEntries(
    Object.entries(filters).filter(
      ([key, value]) =>
        JSON.stringify(value) !==
        JSON.stringify(DEFAULT_FILTERS[key as keyof Filters]),
    ),
  );
}
export function filterChips(
  filters: Filters,
): { key: keyof Filters; label: string }[] {
  const labels: Partial<Record<keyof Filters, string>> = {
    min_rating: "Rating at least",
    min_votes: "Minimum votes",
    min_longevity: "Longevity from",
    max_longevity: "Longevity to",
    price_min: "Price from $",
    price_max: "Price up to $",
    budget_max: "Budget row up to $",
  };
  return Object.entries(compactFilters(filters))
    .filter(([key]) => key !== "min_season_share" || filters.seasons.length)
    .map(([key, value]) => ({
      key: key as keyof Filters,
      label: Array.isArray(value)
        ? `${key.replaceAll("_", " ")}: ${value.map((v) => (v === "male" ? "Men" : v === "female" ? "Women" : v)).join(", ")}`
        : key === "include_clones"
          ? "Clones included"
          : key === "min_season_share"
            ? `Season votes ≥ ${Math.round(Number(value) * 100)}%`
            : key === "store"
              ? "Amazon offers only"
              : `${labels[key as keyof Filters] || key}: ${value}`,
    }));
}
