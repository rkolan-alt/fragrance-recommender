"use client";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import useEmblaCarousel from "embla-carousel-react";
import type {
  Perfume,
  PerfumeDetail,
  Recommendation,
  RecommendationRow,
} from "@/lib/types";
import { amazonUrl, request } from "@/lib/client";
import { Icon } from "./icons";
import { PerfumePhoto } from "./perfume-photo";
const count = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});
const descriptions: Record<string, string> = {
  for_you:
    "Familiar notes. New possibilities. A match for your whole collection.",
  budget:
    "Value finds led by Middle Eastern houses, matched to your taste. Bottles under $60.",
  spring_summer: "Lighter compositions for longer, warmer days.",
  fall_winter: "Depth and warmth for the cooler months.",
  long_lasting: "Fragrances with community-backed staying power.",
  hidden_gems: "Well-loved discoveries beyond the usual suspects.",
};
function Rating({ item }: { item: Recommendation }) {
  return (
    <span className="rating">
      {item.rating_avg ? (
        <>
          <span aria-hidden="true">★</span> {item.rating_avg.toFixed(2)}{" "}
          <small>({count.format(item.vote_count || 0)} votes)</small>
        </>
      ) : (
        <small>Not yet rated</small>
      )}
    </span>
  );
}
function BuyLink({ item }: { item: Recommendation }) {
  const offer = item.best_offer;
  const href = amazonUrl(offer?.url || item.amazon_link?.url);
  if (!href) return null;
  if (!offer)
    return (
      <div className="offer">
        <small>Check bottle size and current price</small>
        <a href={href} target="_blank" rel="noopener noreferrer">
          View on Amazon ↗<span className="sr-only"> (opens in a new tab)</span>
        </a>
      </div>
    );
  return (
    <div className="offer">
      <div>
        <strong>{money.format(offer.price)}</strong>
        <small>
          {Math.round(offer.size_ml)} ml · checked{" "}
          {new Date(offer.fetched_at).toLocaleDateString()}
        </small>
      </div>
      <a href={href} target="_blank" rel="noopener noreferrer">
        Amazon ↗<span className="sr-only"> (opens in a new tab)</span>
      </a>
    </div>
  );
}
export function RecommendationCarousel({
  row,
  collection,
  showDetail,
}: {
  row: RecommendationRow;
  collection: Perfume[];
  showDetail: (item: Recommendation) => void;
}) {
  const [viewport, api] = useEmblaCarousel({
    align: "start",
    slidesToScroll: "auto",
    containScroll: "trimSnaps",
  });
  const [canPrev, setCanPrev] = useState(false);
  const [canNext, setCanNext] = useState(false);
  const id = useId();
  useEffect(() => {
    if (!api) return;
    const update = () => {
      setCanPrev(api.canScrollPrev());
      setCanNext(api.canScrollNext());
    };
    update();
    api.on("select", update);
    api.on("reInit", update);
    return () => {
      api.off("select", update);
      api.off("reInit", update);
    };
  }, [api]);
  return (
    <section className="recommendation-row" aria-labelledby={id}>
      <div className="row-heading">
        <div>
          <h3 id={id}>{row.title}</h3>
          <p>
            {descriptions[row.key] ||
              "Another way to explore the fragrances you love."}
          </p>
        </div>
        {row.items.length > 0 && (
          <div className="carousel-buttons">
            <button
              className="round-button"
              aria-label={`Previous fragrances in ${row.title}`}
              disabled={!canPrev}
              onClick={() => api?.scrollPrev()}
            >
              <Icon name="arrow" className="reverse" />
            </button>
            <button
              className="round-button"
              aria-label={`Next fragrances in ${row.title}`}
              disabled={!canNext}
              onClick={() => api?.scrollNext()}
            >
              <Icon name="arrow" />
            </button>
          </div>
        )}
      </div>
      {row.items.length === 0 ? (
        <div className="row-empty">
          {row.key === "budget"
            ? "No matched bottles under $60 fit this collection yet. Other rows still have discoveries for you."
            : "No matches in this category for your collection right now."}
        </div>
      ) : (
        <div
          className="carousel-viewport"
          ref={viewport}
          tabIndex={0}
          aria-label={`${row.title} fragrances. Use arrow keys to scroll.`}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight") {
              event.preventDefault();
              api?.scrollNext();
            }
            if (event.key === "ArrowLeft") {
              event.preventDefault();
              api?.scrollPrev();
            }
          }}
        >
          <div className="carousel-track">
            {row.items.map((item) => {
              const seed = collection.find(
                (owned) => owned.id === item.because_of,
              );
              const accords = (item.accords || []).slice(0, 4);
              return (
                <article className="fragrance-card" key={item.id}>
                  <button
                    className="scent-art"
                    onClick={() => showDetail(item)}
                    aria-label={`View ${item.brand} ${item.name}`}
                  >
                    <PerfumePhoto perfume={item} variant="card" />
                    <span className="art-arrow" aria-hidden="true">
                      ↗
                    </span>
                  </button>
                  <div className="card-content">
                    <p className="eyebrow brand">{item.brand}</p>
                    <button
                      className="card-name"
                      onClick={() => showDetail(item)}
                    >
                      {item.name}
                    </button>
                    <Rating item={item} />
                    <div className="accord-chips">
                      {accords.slice(0, 3).map((accord) => (
                        <span key={accord.name}>{accord.name}</span>
                      ))}
                    </div>
                    <p className="because">
                      {seed
                        ? `A new direction from ${seed.name}`
                        : "Selected for your collection"}
                      {item.shared_notes.length > 0 && (
                        <span>
                          Shared notes:{" "}
                          {item.shared_notes.slice(0, 2).join(", ")}
                        </span>
                      )}
                    </p>
                    <BuyLink item={item} />
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
export function DetailDialog({
  perfume,
  close,
  actions,
}: {
  perfume: Recommendation;
  close: () => void;
  actions?: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [detail, setDetail] = useState<PerfumeDetail | null>(null);
  const [error, setError] = useState("");
  const title = useId();
  useEffect(() => {
    const node = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    node?.showModal();
    const controller = new AbortController();
    request<PerfumeDetail>(`/api/perfumes/${perfume.id}`, {
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted) setDetail(data);
      })
      .catch((err) => {
        if (!controller.signal.aborted)
          setError(
            err instanceof Error ? err.message : "Couldn’t load details.",
          );
      });
    return () => {
      controller.abort();
      node?.close();
      previous?.focus();
    };
  }, [perfume.id]);
  const data = detail || perfume;
  return (
    <dialog
      className="detail-dialog"
      ref={dialog}
      aria-labelledby={title}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="detail-inner">
        <button
          className="round-button detail-close"
          aria-label="Close fragrance details"
          onClick={close}
        >
          <Icon name="close" />
        </button>
        <PerfumePhoto perfume={data} variant="detail" />
        <p className="eyebrow">{data.brand}</p>
        <h2 id={title}>{data.name}</h2>
        <div className="detail-meta">
          <Rating item={data} />
          {data.gender && (
            <span className="gender">
              {data.gender === "male"
                ? "For men"
                : data.gender === "female"
                  ? "For women"
                  : "Unisex"}
            </span>
          )}
        </div>
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : !detail ? (
          <p className="muted" role="status">
            Opening the note pyramid…
          </p>
        ) : (
          <>
            <h3>Main accords</h3>
            <div className="detail-accords">
              {(detail.accords || []).slice(0, 6).map((accord) => (
                <div key={accord.name}>
                  <span>{accord.name}</span>
                  <div className="bar-track">
                    <span
                      style={{
                        width: `${Math.max(0, Math.min(100, accord.weight))}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <h3>The note pyramid</h3>
            <div className="note-pyramid">
              {(
                [
                  ["Top", detail.notes_top],
                  ["Heart", detail.notes_middle],
                  ["Base", detail.notes_base],
                ] as const
              ).map(([label, notes]) => (
                <div key={label}>
                  <small>{label}</small>
                  <p>
                    {notes?.length
                      ? notes.map((note) => note.name).join(" · ")
                      : "Not recorded"}
                  </p>
                </div>
              ))}
            </div>
            <h3>When to wear it</h3>
            <div className="season-grid">
              {(
                [
                  ["Spring", detail.season_share_spring],
                  ["Summer", detail.season_share_summer],
                  ["Autumn", detail.season_share_autumn],
                  ["Winter", detail.season_share_winter],
                ] as const
              ).map(([name, share]) => (
                <div key={name}>
                  <small>{name}</small>
                  <strong>
                    {share == null ? "—" : `${Math.round(share * 100)}%`}
                  </strong>
                </div>
              ))}
            </div>
            <p className="fine-print">Share of community season votes.</p>
            <div className="longevity">
              <span>Longevity</span>
              <strong>
                {detail.longevity_avg
                  ? `${detail.longevity_avg.toFixed(1)} / 5`
                  : "Not recorded"}
              </strong>
            </div>
          </>
        )}
        <BuyLink item={data} />
        {actions}
        {data.best_offer && (
          <p className="fine-print">
            Observed Amazon listing price. Shipping and tax excluded; price may
            change.
          </p>
        )}
      </div>
    </dialog>
  );
}
