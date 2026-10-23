"use client";
import { useEffect, useRef, useState } from "react";
import { accountRequest } from "./account-client";
import {
  DEFAULT_FILTERS,
  parseFilters,
  compactFilters,
  type Filters,
  type SavedFilter,
} from "./filters-model";
export * from "./filters-model";

export function useFilters(userId: string | null, accountReady: boolean) {
  const [filters, update] = useState<Filters>(DEFAULT_FILTERS);
  const [saved, setSaved] = useState<SavedFilter[]>([]);
  const [identity, setIdentity] = useState<string | null | undefined>(
    undefined,
  );
  const [error, setError] = useState("");
  const preference = useRef<{ explicit: boolean; filters: Filters } | null>(
    null,
  );
  useEffect(() => {
    if (!accountReady) return;
    let active = true;
    async function init() {
      let message = "";
      if (!preference.current) {
        const value = new URLSearchParams(window.location.search).get(
          "filters",
        );
        try {
          preference.current = {
            explicit: value !== null,
            filters:
              value === null
                ? DEFAULT_FILTERS
                : parseFilters(JSON.parse(value)),
          };
        } catch {
          preference.current = { explicit: true, filters: DEFAULT_FILTERS };
          message = "The URL filters were invalid and have been reset.";
        }
      }
      let next: SavedFilter[] = [];
      try {
        if (userId) next = await accountRequest<SavedFilter[]>("me/filters");
      } catch {
        message =
          "Saved filters could not be loaded. Your current filters still work; reopen this page to retry.";
      }
      if (!active) return;
      const defaults = next.find((item) => item.is_default);
      const selected = preference.current.explicit
        ? preference.current.filters
        : defaults
          ? parseFilters(defaults.filter_json)
          : DEFAULT_FILTERS;
      setSaved(next);
      update(selected);
      setError(message);
      setIdentity(userId);
    }
    void init();
    return () => {
      active = false;
    };
  }, [userId, accountReady]);
  const ready = identity === userId && accountReady;
  useEffect(() => {
    if (!ready) return;
    const url = new URL(window.location.href);
    url.searchParams.set("filters", JSON.stringify(compactFilters(filters)));
    window.history.replaceState(null, "", url);
  }, [filters, ready]);
  function setFilters(next: Filters) {
    preference.current = { explicit: true, filters: next };
    update(next);
  }
  return { filters, setFilters, saved, setSaved, ready, error };
}
