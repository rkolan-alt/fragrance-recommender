"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type {
  Perfume,
  PerfumeDetail,
  Recommendation,
  RecommendationRow,
} from "@/lib/types";
import { useAccountCollection } from "@/lib/account";
import { accountRequest } from "@/lib/account-client";
import { AccountControls } from "./account-controls";
import { FilterPanel } from "./filter-panel";
import { useFilters, filterChips, DEFAULT_FILTERS } from "@/lib/filters";
import { request } from "@/lib/client";
import { FragranceSearch } from "./fragrance-search";
import { DetailDialog, RecommendationCarousel } from "./recommendations";
import { Icon } from "./icons";
import { PerfumePhoto } from "./perfume-photo";
const EXAMPLE = [31861, 9099, 9828, 5521, 33519];
export default function FragranceApp() {
  const account = useAccountCollection();
  const { collection, update, warning } = account;
  const preferences = useFilters(account.user?.id || null, account.ready);
  const { filters, setFilters } = preferences;
  const activeFilters = filterChips(filters);
  const [hasDiscovered, setHasDiscovered] = useState(false);
  const [result, setResult] = useState<{
    key: string;
    rows: RecommendationRow[];
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [exampleLoading, setExampleLoading] = useState(false);
  const [error, setError] = useState("");
  const includeClones = filters.include_clones;
  const [detail, setDetail] = useState<Recommendation | null>(null);
  const pending = useRef<AbortController | null>(null);
  const resultArea = useRef<HTMLDivElement>(null);
  const collectionKey = `${account.user?.id || "guest"}:${account.items.map((i) => `${i.perfume_id}:${i.status}:${i.personal_rating}`).join(";")}:${collection
    .map((item) => item.id)
    .sort((a, b) => a - b)
    .join(
      ",",
    )}:${JSON.stringify(filters)}:${JSON.stringify(preferences.saved)}`;
  const currentKey = useRef(collectionKey);
  useEffect(() => {
    currentKey.current = collectionKey;
  }, [collectionKey]);
  useEffect(() => () => pending.current?.abort(), []);
  const rows = result?.key === collectionKey ? result.rows : null;
  function change(next: Perfume[]) {
    pending.current?.abort();
    setLoading(false);
    setError("");
    setResult(null);
    update(next);
  }
  async function example() {
    const startingKey = collectionKey;
    setExampleLoading(true);
    setError("");
    try {
      const data = await Promise.all(
        EXAMPLE.map((id) => request<PerfumeDetail>(`/api/perfumes/${id}`)),
      );
      if (currentKey.current !== startingKey) return;
      change(
        data.map(({ id, name, brand, year, image_url }) => ({
          id,
          name,
          brand,
          year,
          image_url,
        })),
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Couldn’t load the example collection.",
      );
    } finally {
      setExampleLoading(false);
    }
  }
  async function discover(scroll = true) {
    if (collection.length < 5 || !preferences.ready) return;
    setHasDiscovered(true);
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const key = collectionKey;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await (
        account.user
          ? accountRequest<{ rows: RecommendationRow[] }>
          : request<{ rows: RecommendationRow[] }>
      )(account.user ? "recommend" : "/api/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          ...(account.user
            ? {}
            : { owned_ids: collection.map((item) => item.id) }),
          filters,
          limit: 12,
        }),
      });
      if (!controller.signal.aborted && currentKey.current === key) {
        setResult({ key, rows: data.rows });
        if (scroll)
          requestAnimationFrame(() =>
            resultArea.current?.scrollIntoView({
              behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
                .matches
                ? "instant"
                : "smooth",
              block: "start",
            }),
          );
      }
    } catch (err) {
      if (!controller.signal.aborted && currentKey.current === key)
        setError(
          err instanceof Error
            ? err.message
            : "Couldn’t generate recommendations.",
        );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    if (
      account.ready &&
      preferences.ready &&
      (account.user || hasDiscovered || activeFilters.length > 0) &&
      !account.busy &&
      collection.length >= 5
    ) {
      let active = true;
      const timer = setTimeout(() => {
        if (active) void discover(false);
      }, 300);
      return () => {
        active = false;
        clearTimeout(timer);
      };
    }
    // Refresh matches when the persisted collection or personal ratings change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    account.ready,
    account.user?.id,
    account.busy,
    collectionKey,
    preferences.ready,
  ]);
  return (
    <>
      <a href="#collection" className="skip-link">
        Skip to your collection
      </a>
      <header className="site-header">
        <Link
          className="wordmark"
          href="/"
          aria-label="Fragrance Recommender home"
        >
          <span className="logo-mark" aria-hidden="true">
            f.
          </span>
          <span>
            FRAGRANCE<span className="wordmark-sub">RECOMMENDER</span>
          </span>
        </Link>
        <span className="header-note">Good taste starts with you.</span>
        <a className="header-link" href="#collection">
          Your collection{" "}
          <span className="count-badge">{collection.length}</span>
        </a>
        <AccountControls
          user={account.user}
          collection={collection}
          ready={account.ready}
          refresh={account.refresh}
          logout={account.logout}
          locked={account.busy || !account.ready}
        />
      </header>
      <main>
        <section className="hero">
          <div className="hero-copy">
            <p className="eyebrow">
              <span className="small-line" /> A MORE PERSONAL WAY TO DISCOVER
            </p>
            <h1>
              Your next scent.
              <br />
              <em>Already in your nature.</em>
            </h1>
            <p className="hero-description">
              The fragrances you love say a lot. Build your collection, and
              discover what belongs beside it.
            </p>
            <div className="how-it-works">
              <span>
                <b>01</b> Add your fragrances
              </span>
              <span>
                <b>02</b> Find your next favorite
              </span>
            </div>
            <div className="hero-footnote">
              <Icon name="spark" />
              <p>
                Guided by notes, accords, and your taste.
                <br />
                <span>Balanced with community ratings and popularity.</span>
              </p>
            </div>
          </div>
          <section
            className="collection-panel"
            id="collection"
            aria-labelledby="collection-title"
          >
            <div className="panel-heading">
              <div>
                <p className="eyebrow">YOUR STARTING POINT</p>
                <h2 id="collection-title">The collection</h2>
              </div>
              <span className="collection-number">
                {String(collection.length).padStart(2, "0")}
                <small> / 05 min.</small>
              </span>
            </div>
            <fieldset
              disabled={!account.ready || account.busy}
              className="collection-fieldset"
            >
              <FragranceSearch
                owned={collection}
                add={(perfume) => change([...collection, perfume])}
              />
              {collection.length ? (
                <>
                  <ul
                    className="collection-list"
                    aria-label="Your fragrance collection"
                  >
                    {collection.map((perfume, index) => (
                      <li key={perfume.id}>
                        <span className="collection-index">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <PerfumePhoto perfume={perfume} variant="thumb" />
                        <div>
                          <small>{perfume.brand}</small>
                          <button
                            className="collection-name"
                            aria-label={`View details for ${perfume.brand} ${perfume.name}`}
                            onClick={() =>
                              setDetail({
                                ...perfume,
                                because_of: perfume.id,
                                shared_notes: [],
                                shared_accords: [],
                                best_offer: null,
                              })
                            }
                          >
                            {perfume.name}
                          </button>
                        </div>
                        {account.user && (
                          <label className="personal-rating">
                            <span className="sr-only">
                              Your rating for {perfume.name}
                            </span>
                            <select
                              aria-label={`Your rating for ${perfume.name}`}
                              value={
                                account.items.find(
                                  (i) => i.perfume_id === perfume.id,
                                )?.personal_rating || ""
                              }
                              onChange={(e) =>
                                account.save(
                                  perfume,
                                  "owned",
                                  e.target.value
                                    ? Number(e.target.value)
                                    : null,
                                )
                              }
                            >
                              <option value="">Rate</option>
                              {[1, 2, 3, 4, 5].map((n) => (
                                <option key={n} value={n}>
                                  {n} ★
                                </option>
                              ))}
                            </select>
                          </label>
                        )}
                        <button
                          className="icon-button remove-button"
                          aria-label={`Remove ${perfume.brand} ${perfume.name}`}
                          onClick={() =>
                            change(
                              collection.filter(
                                (item) => item.id !== perfume.id,
                              ),
                            )
                          }
                        >
                          <Icon name="close" />
                        </button>
                      </li>
                    ))}
                  </ul>
                  <p className="storage-note">
                    <Icon name="check" />
                    {account.user
                      ? account.busy
                        ? "Saving to your account…"
                        : "Saved to your account"
                      : warning
                        ? "Saved for this visit"
                        : "Saved in this browser"}
                  </p>
                </>
              ) : (
                <div className="collection-empty">
                  <div className="empty-symbol" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                  <p>
                    A little of your taste.
                    <br />A world of possibilities.
                  </p>
                  <small>Add at least 5 fragrances to get started.</small>
                </div>
              )}
              {warning && (
                <p className="fine-print" role="status">
                  {warning}
                </p>
              )}
              <div className="collection-bottom">
                <div
                  className="progress-track"
                  role="progressbar"
                  aria-label="Fragrances added toward five minimum"
                  aria-valuemin={0}
                  aria-valuemax={5}
                  aria-valuenow={Math.min(5, collection.length)}
                >
                  <span
                    style={{
                      width: `${Math.min(100, collection.length * 20)}%`,
                    }}
                  />
                </div>
                <p className="progress-copy" aria-live="polite">
                  {collection.length >= 5
                    ? "Your collection is ready to explore."
                    : `${5 - collection.length} more fragrance${5 - collection.length === 1 ? "" : "s"} to start discovering.`}
                </p>
                <label className="clone-toggle">
                  <input
                    type="checkbox"
                    checked={includeClones}
                    onChange={(event) => {
                      pending.current?.abort();
                      setLoading(false);
                      setError("");
                      setFilters({
                        ...filters,
                        include_clones: event.target.checked,
                      });
                    }}
                  />
                  <span>Include clone fragrances</span>
                </label>
                <button
                  className="primary-button"
                  onClick={() => discover()}
                  disabled={
                    collection.length < 5 ||
                    loading ||
                    exampleLoading ||
                    !account.ready ||
                    !preferences.ready ||
                    account.busy
                  }
                >
                  {loading
                    ? "Finding your next favorites…"
                    : "Discover my matches"}
                  {!loading && <Icon name="arrow" />}
                </button>
                {collection.length === 0 && (
                  <button
                    className="example-button"
                    onClick={example}
                    disabled={exampleLoading}
                  >
                    {exampleLoading
                      ? "Opening the example…"
                      : "Just exploring? Try an example collection"}
                  </button>
                )}
                {error && (
                  <p className="error" role="alert">
                    {error}
                  </p>
                )}
              </div>
            </fieldset>
            {account.error && (
              <p className="error" role="alert">
                {account.error}{" "}
                <button onClick={() => account.refresh()}>
                  Retry account sync
                </button>
              </p>
            )}
            {account.user &&
              account.items.some((item) => item.status !== "owned") && (
                <div className="saved-shelf">
                  <h3>Your saved fragrances</h3>
                  {account.items
                    .filter((item) => item.status !== "owned")
                    .map((item) => (
                      <div className="saved-item" key={item.perfume_id}>
                        <PerfumePhoto perfume={item.perfume} variant="thumb" />
                        <span>
                          <small>
                            {item.status === "wishlist"
                              ? "Wishlist"
                              : "Disliked"}{" "}
                            · {item.perfume.brand}
                          </small>
                          <strong>{item.perfume.name}</strong>
                        </span>
                        <button
                          onClick={() => account.save(item.perfume, "owned")}
                          disabled={account.busy}
                        >
                          Mark owned
                        </button>
                      </div>
                    ))}
                </div>
              )}
          </section>
        </section>
        <section
          className="discoveries"
          ref={resultArea}
          aria-labelledby="discoveries-title"
          aria-busy={loading}
        >
          <div className="discovery-intro">
            <div>
              <p className="eyebrow">THE NEXT CHAPTER</p>
              <h2 id="discoveries-title">
                {rows
                  ? "Chosen for your collection."
                  : "Familiar. Unexpected. Unmistakably you."}
              </h2>
            </div>
            <span className="section-tag">COLLECTION-LED DISCOVERY</span>
          </div>
          <div className="filter-toolbar">
            <div>
              <p className="filter-summary">
                {activeFilters.length
                  ? `${activeFilters.length} filter groups active`
                  : "A little more specific? Make these discoveries your own."}
              </p>
              <div className="active-filters" aria-label="Active filters">
                {activeFilters.map((chip) => (
                  <button
                    key={chip.key}
                    aria-label={`Remove filter: ${chip.label}`}
                    onClick={() =>
                      setFilters({
                        ...filters,
                        [chip.key]: DEFAULT_FILTERS[chip.key],
                      })
                    }
                  >
                    {chip.label} ×
                  </button>
                ))}
              </div>
            </div>
            <div className="filter-toolbar-actions">
              <FilterPanel
                filters={filters}
                onChange={setFilters}
                userId={account.user?.id || null}
                saved={preferences.saved}
                onSaved={preferences.setSaved}
                disabled={!preferences.ready || account.busy}
              />
              {activeFilters.length > 0 && (
                <button
                  className="reset-filters"
                  onClick={() => setFilters(DEFAULT_FILTERS)}
                >
                  Clear all filters
                </button>
              )}
            </div>
          </div>
          {preferences.error && (
            <p className="error" role="status">
              {preferences.error}
            </p>
          )}
          {loading ? (
            <div className="recommendation-loading" role="status">
              <span className="spinner" /> Finding connections in your
              collection…
            </div>
          ) : rows ? (
            <>
              <p className="results-note" role="status">
                Your collection, explored from {rows.length} different angles.
                Select a fragrance to see its notes.
              </p>
              {rows.map((row) => (
                <RecommendationCarousel
                  key={`${collectionKey}-${row.key}`}
                  row={row}
                  collection={collection}
                  showDetail={setDetail}
                  budgetMax={Math.min(
                    filters.budget_max,
                    filters.price_max ?? filters.budget_max,
                  )}
                />
              ))}
            </>
          ) : (
            <div className="discovery-preview">
              {[
                {
                  number: "01",
                  title: "For your whole collection",
                  description:
                    "The notes and accords that tie your taste together.",
                  mark: "◎",
                },
                {
                  number: "02",
                  title: "For a change of season",
                  description:
                    "Bright days, cooler nights, and everything in between.",
                  mark: "◐",
                },
                {
                  number: "03",
                  title: "For something different",
                  description: "A thoughtful step outside your comfort zone.",
                  mark: "✳",
                },
              ].map((item) => (
                <div className="preview-item" key={item.number}>
                  <div>
                    <span className="eyebrow">{item.number}</span>
                    <span className="preview-mark" aria-hidden="true">
                      {item.mark}
                    </span>
                  </div>
                  <h3>{item.title}</h3>
                  <p>{item.description}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
      <footer>
        <a className="footer-brand" href="#">
          Fragrance Recommender
        </a>
        <p>Your taste. A little discovery.</p>
        <span>
          Data:{" "}
          <a
            href="https://www.kaggle.com/datasets/ledecanteur/fragrantica-perfumes"
            target="_blank"
            rel="noopener noreferrer"
          >
            Le Decanteur / Fragrantica
          </a>{" "}
          ·{" "}
          <a
            href="https://creativecommons.org/licenses/by-nc-sa/4.0/"
            target="_blank"
            rel="noopener noreferrer"
          >
            CC BY-NC-SA 4.0
          </a>
        </span>
      </footer>
      {detail && (
        <DetailDialog
          key={detail.id}
          perfume={detail}
          close={() => setDetail(null)}
          actions={
            account.user ? (
              <div className="detail-account-actions">
                {(["owned", "wishlist", "disliked"] as const).map((status) => (
                  <button
                    className="secondary-button"
                    key={status}
                    disabled={
                      account.busy ||
                      account.items.some(
                        (i) =>
                          i.perfume_id === detail.id && i.status === status,
                      )
                    }
                    onClick={() => account.save(detail, status)}
                  >
                    {status === "owned"
                      ? "Add to collection"
                      : status === "wishlist"
                        ? "Save to wishlist"
                        : "Dislike"}
                  </button>
                ))}
                {account.error && (
                  <p className="error" role="alert">
                    {account.error}
                  </p>
                )}
              </div>
            ) : undefined
          }
        />
      )}
    </>
  );
}
