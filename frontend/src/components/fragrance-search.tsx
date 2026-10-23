"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { Perfume } from "@/lib/types";
import { request } from "@/lib/client";
import { Icon } from "./icons";
import { PerfumePhoto } from "./perfume-photo";

export function FragranceSearch({
  owned,
  add,
}: {
  owned: Perfume[];
  add: (perfume: Perfume) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Perfume[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">(
    "idle",
  );
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setActive(-1);
      setResults([]);
      if (query.trim().length < 2) {
        setStatus("idle");
        return;
      }
      setStatus("loading");
      try {
        const data = await request<Perfume[]>(
          `/api/search?q=${encodeURIComponent(query.trim())}`,
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) {
          setResults(data);
          setStatus("ready");
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          setStatus("error");
          setError(
            err instanceof Error ? err.message : "Search is unavailable.",
          );
        }
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);
  useEffect(() => {
    if (open && active >= 0)
      document
        .getElementById(`${id}-${active}`)
        ?.scrollIntoView({ block: "nearest" });
  }, [active, open, id]);
  const visible = open && query.trim().length >= 2;
  function choose(perfume: Perfume) {
    if (owned.some((item) => item.id === perfume.id) || owned.length >= 500)
      return;
    add(perfume);
    setQuery("");
    setResults([]);
    setOpen(false);
    input.current?.focus();
  }
  return (
    <div className="search" ref={root}>
      <label htmlFor={`${id}-input`} className="field-label">
        Find a fragrance you own
      </label>
      <div className={`search-box ${visible ? "is-open" : ""}`}>
        <Icon name="search" />
        <input
          id={`${id}-input`}
          ref={input}
          role="combobox"
          autoComplete="off"
          maxLength={200}
          aria-controls={`${id}-results`}
          aria-expanded={visible}
          aria-autocomplete="list"
          aria-activedescendant={
            visible && active >= 0 && results[active]
              ? `${id}-${active}`
              : undefined
          }
          placeholder="Try Dior Sauvage or your favorite brand…"
          value={query}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            setActive(-1);
            setResults([]);
            setStatus("idle");
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setOpen(false);
              setActive(-1);
            }
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
              setActive((current) => {
                if (!results.length) return -1;
                if (current < 0)
                  return event.key === "ArrowDown" ? 0 : results.length - 1;
                return (
                  (current +
                    (event.key === "ArrowDown" ? 1 : -1) +
                    results.length) %
                  results.length
                );
              });
            }
            if (
              event.key === "Enter" &&
              visible &&
              active >= 0 &&
              results[active]
            ) {
              event.preventDefault();
              choose(results[active]);
            }
          }}
        />
        {query && (
          <button
            className="icon-button"
            type="button"
            aria-label="Clear search"
            onClick={() => {
              setQuery("");
              input.current?.focus();
            }}
          >
            <Icon name="close" />
          </button>
        )}
      </div>
      {visible && (
        <div className="search-popover">
          <p className="search-status" role="status">
            {status === "loading" || status === "idle"
              ? "Searching the catalog…"
              : status === "error"
                ? error
                : results.length
                  ? "Select to add to your collection"
                  : "No matches. Try the brand or a shorter fragrance name."}
          </p>
          <ul
            id={`${id}-results`}
            role="listbox"
            aria-label="Fragrance search results"
          >
            {results.map((perfume, index) => {
              const added = owned.some((item) => item.id === perfume.id);
              return (
                <li
                  key={perfume.id}
                  id={`${id}-${index}`}
                  role="option"
                  aria-selected={active === index}
                  className={active === index ? "active" : ""}
                >
                  <button
                    type="button"
                    tabIndex={-1}
                    disabled={added || owned.length >= 500}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(perfume)}
                  >
                    <PerfumePhoto perfume={perfume} variant="thumb" />
                    <span className="search-result-name">
                      <small>{perfume.brand}</small>
                      <strong>{perfume.name}</strong>
                      {perfume.year && (
                        <span className="search-year">{perfume.year}</span>
                      )}
                    </span>
                    {added ? (
                      <span className="added-label">
                        Added <Icon name="check" />
                      </span>
                    ) : (
                      <Icon name="plus" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
