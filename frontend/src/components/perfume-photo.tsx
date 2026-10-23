"use client";
import Image from "next/image";
import { useEffect, useState } from "react";
import type { Perfume } from "@/lib/types";
import { request } from "@/lib/client";

function photoUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      url.host === "fimgs.net" &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash &&
      /^\/mdimg\/perfume\/(375x500|m)\.\d+\.jpg$/.test(url.pathname)
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function PerfumePhoto({
  perfume,
  variant,
}: {
  perfume: Perfume;
  variant: "thumb" | "card" | "detail";
}) {
  const direct = photoUrl(perfume.image_url);
  const [restored, setRestored] = useState<{
    id: number;
    url: string | null;
  } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  // Collections saved before images were introduced contain only id/name/brand.
  useEffect(() => {
    if (perfume.image_url !== undefined) return;
    const controller = new AbortController();
    request<Perfume>(`/api/perfumes/${perfume.id}`, {
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted)
          setRestored({ id: perfume.id, url: photoUrl(data.image_url) });
      })
      .catch(() => {
        /* Missing metadata leaves the accessible placeholder in place. */
      });
    return () => controller.abort();
  }, [perfume.id, perfume.image_url]);
  const src = direct || (restored?.id === perfume.id ? restored.url : null);
  return (
    <span className={`perfume-photo photo-${variant}`}>
      {src && failed !== src ? (
        <Image
          src={src}
          width={375}
          height={500}
          unoptimized
          loading="lazy"
          referrerPolicy="no-referrer"
          alt={`${perfume.brand} ${perfume.name} bottle`}
          onError={() => setFailed(src)}
        />
      ) : (
        <span
          className="photo-placeholder"
          role="img"
          aria-label={`Photo unavailable for ${perfume.brand} ${perfume.name}`}
        >
          <svg viewBox="0 0 40 56" fill="none" aria-hidden="true">
            <path
              d="M14 3h12v10H14zM11 13h18v5H11zM7 18h26v34H7z"
              stroke="currentColor"
            />
            <path d="M12 30h16v12H12z" stroke="currentColor" />
          </svg>
          {variant !== "thumb" && <small>Photo unavailable</small>}
        </span>
      )}
    </span>
  );
}
