import "server-only";

const base = (process.env.FRAGRANCE_API_URL || "http://127.0.0.1:8001").replace(
  /\/$/,
  "",
);

// Guest endpoints deliberately forward neither browser cookies nor credentials.
export async function backend(path: string, init: RequestInit = {}) {
  try {
    const response = await fetch(`${base}${path}`, {
      ...init,
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
      headers: { "Content-Type": "application/json" },
    });
    const data = await response.json();
    return Response.json(data, {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json(
      {
        detail:
          "The fragrance service is unavailable. Please try again shortly.",
      },
      { status: 503 },
    );
  }
}
