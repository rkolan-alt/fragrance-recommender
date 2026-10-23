"use client";
import { useEffect, useRef, useState } from "react";
import { AccountError, accountRequest } from "./account-client";
import { parseCollection, useCollection } from "./collection";
import type { Perfume } from "./types";
export type User = { id: string; email: string; is_verified: boolean };
export type SavedItem = {
  perfume_id: number;
  status: "owned" | "wishlist" | "disliked";
  personal_rating: number | null;
  perfume: Perfume;
};

export function useAccountCollection() {
  const guest = useCollection();
  const guestRef = useRef(guest);
  useEffect(() => {
    guestRef.current = guest;
  });
  const [user, setUser] = useState<User | null>(null);
  const [items, setItems] = useState<SavedItem[]>([]);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);

  async function load() {
    const next = await accountRequest<SavedItem[]>("me/collection");
    setItems(next);
  }
  async function refresh() {
    const current = ++generation.current;
    setReady(false);
    setError("");
    let available = false;
    try {
      const who = await accountRequest<User>("users/me");
      if (current !== generation.current) return;
      setUser(who);
      const local = guestRef.current.collection;
      if (local.length) {
        await accountRequest("me/collection/import", {
          method: "POST",
          body: JSON.stringify({
            items: local.map((item) => ({ perfume_id: item.id })),
          }),
        });
        guestRef.current.update([]);
      }
      await load();
      available = true;
    } catch (err) {
      if (current !== generation.current) return;
      if (err instanceof AccountError && err.status === 401) {
        setUser(null);
        setItems([]);
        available = true;
      } else
        setError(
          err instanceof Error ? err.message : "Couldn’t load your account.",
        );
    } finally {
      if (current === generation.current) setReady(available);
    }
  }
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void refresh();
    });
    const counter = generation;
    return () => {
      active = false;
      counter.current++;
    };
    // Initial session check; later checks follow explicit account actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(
    perfume: Perfume,
    status: SavedItem["status"],
    personal_rating?: number | null,
  ) {
    if (!user || busy || !ready) return;
    setBusy(true);
    setError("");
    try {
      const exists = items.some((item) => item.perfume_id === perfume.id);
      await accountRequest(
        exists ? `me/collection/${perfume.id}` : "me/collection",
        {
          method: exists ? "PATCH" : "POST",
          body: JSON.stringify({
            ...(exists ? {} : { perfume_id: perfume.id }),
            status,
            ...(personal_rating === undefined ? {} : { personal_rating }),
          }),
        },
      );
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Couldn’t save your collection.",
      );
    } finally {
      setBusy(false);
    }
  }
  const collection = user
    ? items
        .filter((item) => item.status === "owned")
        .map((item) => item.perfume)
    : guest.collection;
  async function update(next: Perfume[]) {
    if (!user) {
      guest.update(next);
      return;
    }
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      for (const item of collection.filter(
        (item) => !next.some((p) => p.id === item.id),
      ))
        await accountRequest(`me/collection/${item.id}`, { method: "DELETE" });
      for (const item of next.filter(
        (item) => !collection.some((p) => p.id === item.id),
      )) {
        const exists = items.some((saved) => saved.perfume_id === item.id);
        await accountRequest(
          exists ? `me/collection/${item.id}` : "me/collection",
          {
            method: exists ? "PATCH" : "POST",
            body: JSON.stringify(
              exists ? { status: "owned" } : { perfume_id: item.id },
            ),
          },
        );
      }
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Couldn’t save your collection.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    if (busy || !ready) return;
    setBusy(true);
    try {
      await accountRequest("auth/logout", { method: "POST" });
      generation.current++;
      setUser(null);
      setItems([]);
    } finally {
      setBusy(false);
    }
  }
  return {
    user,
    items,
    collection,
    update,
    save,
    refresh,
    logout,
    ready,
    busy,
    error,
    warning: user ? "" : guest.warning,
    parseCollection,
  };
}
