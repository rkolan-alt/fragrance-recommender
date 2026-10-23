"use client";
import { useMemo, useState, useSyncExternalStore } from "react";
import type { Perfume } from "./types";
const KEY = "fragrance-collection:v1";
const EVENT = "fragrance-collection-change";
function subscribe(notify: () => void) {
  const storage = (event: StorageEvent) => {
    if (event.key === KEY || event.key === null) notify();
  };
  window.addEventListener("storage", storage);
  window.addEventListener(EVENT, notify);
  return () => {
    window.removeEventListener("storage", storage);
    window.removeEventListener(EVENT, notify);
  };
}
function snapshot() {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}
export function parseCollection(raw: string | null): Perfume[] {
  try {
    const data: unknown = JSON.parse(raw || "[]");
    if (!Array.isArray(data)) return [];
    const seen = new Set<number>();
    return data
      .filter((item): item is Perfume => {
        if (
          !item ||
          !Number.isSafeInteger(item.id) ||
          item.id <= 0 ||
          typeof item.name !== "string" ||
          typeof item.brand !== "string" ||
          item.name.length > 500 ||
          item.brand.length > 500 ||
          seen.has(item.id)
        )
          return false;
        seen.add(item.id);
        return true;
      })
      .slice(0, 500)
      .map(({ id, name, brand, year, image_url }) => ({
        id,
        name,
        brand,
        year,
        image_url,
      }));
  } catch {
    return [];
  }
}
export function useCollection() {
  const raw = useSyncExternalStore(subscribe, snapshot, () => null);
  const saved = useMemo(() => parseCollection(raw), [raw]);
  const [temporary, setTemporary] = useState<Perfume[] | null>(null);
  const [warning, setWarning] = useState("");
  function update(next: Perfume[]) {
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
      setTemporary(null);
      setWarning("");
      window.dispatchEvent(new Event(EVENT));
    } catch {
      setTemporary(next);
      setWarning(
        "Browser storage is unavailable. Your collection will last for this visit only.",
      );
    }
  }
  return { collection: temporary ?? saved, update, warning };
}
