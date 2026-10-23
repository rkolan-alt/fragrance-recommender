"use client";
import { useEffect, useId, useRef, useState } from "react";
import { accountRequest } from "@/lib/account-client";
import { request } from "@/lib/client";
import {
  DEFAULT_FILTERS,
  parseFilters,
  type Filters,
  type FilterOptions,
  type SavedFilter,
} from "@/lib/filters";

function TermPicker({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: string[];
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const choices = options
    .filter(
      (v) =>
        !value.includes(v) && v.toLowerCase().includes(query.toLowerCase()),
    )
    .slice(0, 8);
  function choose(term: string) {
    if (value.length >= 100) return;
    onChange([...value, term]);
    setQuery("");
    setOpen(false);
    setActive(-1);
    input.current?.focus();
  }
  return (
    <div
      className="term-picker"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        ref={input}
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-options`}
        aria-autocomplete="list"
        aria-activedescendant={
          open && active >= 0 && choices[active] ? `${id}-${active}` : undefined
        }
        autoComplete="off"
        placeholder={`Search ${label.toLowerCase()}…`}
        value={query}
        maxLength={200}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setOpen(true);
            setActive((i) =>
              choices.length
                ? (i + (e.key === "ArrowDown" ? 1 : -1) + choices.length) %
                  choices.length
                : -1,
            );
          }
          if (e.key === "Enter") {
            e.preventDefault();
            const exact = choices.find(
              (v) => v.toLowerCase() === query.toLowerCase(),
            );
            if (active >= 0 && choices[active]) choose(choices[active]);
            else if (exact) choose(exact);
          }
          if (e.key === "Escape" && open) {
            e.preventDefault();
            e.stopPropagation();
            setOpen(false);
          }
        }}
      />
      {open && (
        <div
          className="term-options"
          id={`${id}-options`}
          role="listbox"
          aria-label={label}
        >
          {choices.length ? (
            choices.map((term, index) => (
              <button
                type="button"
                role="option"
                aria-selected={index === active}
                id={`${id}-${index}`}
                key={term}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(term)}
              >
                {term}
              </button>
            ))
          ) : (
            <p>No matching choices.</p>
          )}
        </div>
      )}
      <div className="selected-terms">
        {value.map((term) => (
          <button
            type="button"
            key={term}
            aria-label={`Remove ${term} from ${label.toLowerCase()}`}
            onClick={() => onChange(value.filter((v) => v !== term))}
          >
            {term} ×
          </button>
        ))}
      </div>
    </div>
  );
}

export function FilterPanel({
  filters,
  onChange,
  userId,
  saved,
  onSaved,
  disabled,
}: {
  filters: Filters;
  onChange: (filters: Filters) => void;
  userId: string | null;
  saved: SavedFilter[];
  onSaved: (items: SavedFilter[]) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(filters);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [optionsError, setOptionsError] = useState("");
  const [optionAttempt, setOptionAttempt] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [saveMode, setSaveMode] = useState("preset");
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    node?.showModal();
    return () => {
      node?.close();
      previous?.focus();
    };
  }, [open]);
  useEffect(() => {
    if (!open || options) return;
    const controller = new AbortController();
    request<FilterOptions>("/api/filter-options", { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) {
          setOptions(data);
          setOptionsError("");
        }
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setOptionsError("Scent choices could not be loaded.");
      });
    return () => controller.abort();
  }, [open, options, optionAttempt]);
  function field<K extends keyof Filters>(key: K, value: Filters[K]) {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setError("");
    setMessage("");
  }
  function validate() {
    const next = parseFilters(draft);
    if (options) {
      for (const [terms, vocab] of [
        [next.include_accords, options.accords],
        [next.exclude_accords, options.accords],
        [next.include_notes, options.notes],
        [next.exclude_notes, options.notes],
        [next.exclude_brands, options.brands],
      ])
        if (terms.some((term) => !vocab.includes(term)))
          throw new Error(
            "A saved scent choice is no longer in the catalog. Remove it and try again.",
          );
    }
    return next;
  }
  async function save() {
    setError("");
    setMessage("");
    setBusy(true);
    try {
      const next = validate();
      if (!name.trim()) throw new Error("Give these filters a name.");
      await accountRequest("me/filters", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          filter_json: next,
          is_default: saveMode === "default",
          is_custom_row: saveMode === "row",
        }),
      });
      const updated = await accountRequest<SavedFilter[]>("me/filters");
      onSaved(updated);
      if (saveMode !== "row") onChange(next);
      setName("");
      setMessage(
        saveMode === "row"
          ? "Custom row saved. It appears below your main recommendations."
          : "Filters saved to your account.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t save filters.");
    } finally {
      setBusy(false);
    }
  }
  async function remove(item: SavedFilter) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await accountRequest(`me/filters/${item.id}`, { method: "DELETE" });
      onSaved(saved.filter((v) => v.id !== item.id));
      setMessage("Saved filters removed.");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Couldn’t remove saved filters.",
      );
    } finally {
      setBusy(false);
    }
  }
  function numeric(
    key:
      | "min_rating"
      | "min_votes"
      | "min_longevity"
      | "max_longevity"
      | "price_min"
      | "price_max"
      | "budget_max",
    label: string,
    min: number,
    max: number,
    step: number,
  ) {
    return (
      <label className="filter-number">
        {label}
        <input
          type="number"
          min={min}
          max={max}
          step={step}
          value={draft[key] ?? ""}
          placeholder="Any"
          onChange={(e) =>
            field(
              key,
              e.target.value === ""
                ? key === "budget_max"
                  ? 60
                  : null
                : Number(e.target.value),
            )
          }
        />
      </label>
    );
  }
  return (
    <>
      <button
        className="secondary-button customize-button"
        disabled={disabled}
        onClick={() => {
          setDraft(filters);
          setError("");
          setMessage("");
          setOpen(true);
        }}
      >
        Customize filters
      </button>
      {open && (
        <dialog
          ref={dialog}
          className="filter-dialog"
          aria-labelledby={title}
          onCancel={(e) => {
            e.preventDefault();
            if (!busy) setOpen(false);
          }}
        >
          <div className="filter-heading">
            <div>
              <p className="eyebrow">MAKE ROOM FOR YOUR TASTE</p>
              <h2 id={title}>Refine your discoveries.</h2>
            </div>
            <button
              className="round-button"
              aria-label="Close filters"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              ×
            </button>
          </div>
          <p className="fine-print">
            These limits apply to every row. Custom rows must also satisfy their
            saved criteria.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              try {
                onChange(validate());
                setOpen(false);
              } catch (err) {
                setError(
                  err instanceof Error ? err.message : "Check your filters.",
                );
              }
            }}
          >
            <fieldset disabled={busy} className="filter-fields">
              <section>
                <h3>Who & when</h3>
                <fieldset className="filter-toggles">
                  <legend>Gender</legend>
                  {[
                    ["male", "Men"],
                    ["female", "Women"],
                    ["unisex", "Unisex"],
                  ].map(([value, label]) => (
                    <label key={value}>
                      <input
                        type="checkbox"
                        checked={draft.genders.includes(value)}
                        onChange={(e) =>
                          field(
                            "genders",
                            e.target.checked
                              ? [...draft.genders, value]
                              : draft.genders.filter((v) => v !== value),
                          )
                        }
                      />
                      {label}
                    </label>
                  ))}
                </fieldset>
                <fieldset className="filter-toggles">
                  <legend>Seasons</legend>
                  {["spring", "summer", "autumn", "winter"].map((value) => (
                    <label key={value}>
                      <input
                        type="checkbox"
                        checked={draft.seasons.includes(value)}
                        onChange={(e) =>
                          field(
                            "seasons",
                            e.target.checked
                              ? [...draft.seasons, value]
                              : draft.seasons.filter((v) => v !== value),
                          )
                        }
                      />
                      {value === "autumn"
                        ? "Fall"
                        : value[0].toUpperCase() + value.slice(1)}
                    </label>
                  ))}
                </fieldset>
                {draft.seasons.length > 0 && (
                  <label className="season-share">
                    Combined season votes:{" "}
                    {Math.round(draft.min_season_share * 100)}% minimum
                    <input
                      type="range"
                      aria-label="Minimum selected season vote share"
                      min="0"
                      max="1"
                      step="0.05"
                      value={draft.min_season_share}
                      onChange={(e) =>
                        field("min_season_share", Number(e.target.value))
                      }
                    />
                    <small>
                      Votes across the selected seasons are added together.
                    </small>
                  </label>
                )}
              </section>
              <section>
                <h3>Community & staying power</h3>
                <div className="filter-grid">
                  {numeric("min_rating", "Minimum rating (0–5)", 0, 5, 0.1)}
                  {numeric("min_votes", "Minimum rating votes", 0, 1e9, 1)}
                  {numeric(
                    "min_longevity",
                    "Minimum longevity (1–5)",
                    1,
                    5,
                    0.1,
                  )}
                  {numeric(
                    "max_longevity",
                    "Maximum longevity (1–5)",
                    1,
                    5,
                    0.1,
                  )}
                </div>
              </section>
              <section>
                <h3>Price & value</h3>
                <div className="filter-grid">
                  {numeric("price_min", "Minimum price ($)", 0, 10000, 0.01)}
                  {numeric("price_max", "Maximum price ($)", 0, 10000, 0.01)}
                  {numeric(
                    "budget_max",
                    "Budget row limit ($)",
                    0.01,
                    10000,
                    0.01,
                  )}
                  <label className="filter-number">
                    Availability
                    <select
                      value={draft.store}
                      onChange={(e) =>
                        field("store", e.target.value as Filters["store"])
                      }
                    >
                      <option value="any">Include unpriced fragrances</option>
                      <option value="amazon">
                        Confirmed Amazon prices only
                      </option>
                    </select>
                  </label>
                </div>
                <p className="fine-print">
                  Price limits use cached Amazon bottle prices and hide
                  fragrances without a confirmed price. Prices exclude shipping
                  and tax.
                </p>
              </section>
              <section>
                <h3>The scent itself</h3>
                <p className="fine-print">
                  Required accords and notes must all be present. Any excluded
                  scent rules out a fragrance. Notes match across top, heart and
                  base.
                </p>
                {options ? (
                  <div className="filter-grid">
                    {(
                      [
                        [
                          "include_accords",
                          "Required accords",
                          options.accords,
                        ],
                        [
                          "exclude_accords",
                          "Excluded accords",
                          options.accords,
                        ],
                        ["include_notes", "Required notes", options.notes],
                        ["exclude_notes", "Excluded notes", options.notes],
                        ["exclude_brands", "Excluded brands", options.brands],
                      ] as const
                    ).map(([key, label, vocab]) => (
                      <TermPicker
                        key={key}
                        label={label}
                        options={vocab}
                        value={draft[key]}
                        onChange={(value) => field(key, value)}
                      />
                    ))}
                  </div>
                ) : optionsError ? (
                  <p className="error">
                    {optionsError}{" "}
                    <button
                      type="button"
                      onClick={() => setOptionAttempt((n) => n + 1)}
                    >
                      Retry scent choices
                    </button>
                  </p>
                ) : (
                  <p role="status">Loading accord and note choices…</p>
                )}
                <label className="clone-toggle">
                  <input
                    type="checkbox"
                    checked={draft.include_clones}
                    onChange={(e) => field("include_clones", e.target.checked)}
                  />
                  Include clone fragrances
                </label>
              </section>
              {userId ? (
                <section>
                  <h3>Keep this combination</h3>
                  <div className="filter-grid">
                    <label className="filter-number">
                      Filter name
                      <input
                        value={name}
                        maxLength={100}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="e.g. Fresh office scents"
                      />
                    </label>
                    <label className="filter-number">
                      Save as
                      <select
                        value={saveMode}
                        onChange={(e) => setSaveMode(e.target.value)}
                      >
                        <option value="preset">Named preset</option>
                        <option value="default">My default filters</option>
                        <option value="row">Custom recommendation row</option>
                      </select>
                    </label>
                  </div>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={save}
                    disabled={busy}
                  >
                    Save filters
                  </button>
                  {saved.length > 0 && (
                    <ul className="saved-filters" aria-label="Saved filters">
                      {saved.map((item) => (
                        <li key={item.id}>
                          <button
                            type="button"
                            onClick={() => {
                              try {
                                const next = parseFilters(item.filter_json);
                                setDraft(next);
                                onChange(next);
                                setMessage(`Loaded ${item.name}.`);
                              } catch {
                                setError(
                                  "These saved filters are invalid. Remove them and create a new set.",
                                );
                              }
                            }}
                          >
                            {item.name}{" "}
                            <small>
                              {item.is_default
                                ? "Default"
                                : item.is_custom_row
                                  ? "Custom row"
                                  : "Preset"}
                            </small>
                          </button>
                          <button
                            type="button"
                            aria-label={`Delete saved filter ${item.name}`}
                            onClick={() => remove(item)}
                          >
                            Remove
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              ) : (
                <p className="fine-print">
                  Sign in to save presets, defaults, and custom rows. Guest
                  filters are kept in this page’s URL.
                </p>
              )}
            </fieldset>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            {message && (
              <p className="fine-print" role="status">
                {message}
              </p>
            )}
            <div className="filter-footer">
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() => {
                  setDraft(DEFAULT_FILTERS);
                  setError("");
                  setMessage("");
                }}
              >
                Reset filters
              </button>
              <button className="primary-button" disabled={busy}>
                Apply filters
              </button>
            </div>
          </form>
        </dialog>
      )}
    </>
  );
}
