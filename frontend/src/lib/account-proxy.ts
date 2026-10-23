import "server-only";

const base = (process.env.FRAGRANCE_API_URL || "http://127.0.0.1:8001").replace(
  /\/$/,
  "",
);
const allowed: Record<string, string[]> = {
  "auth/options": ["GET"],
  "auth/csrf": ["GET"],
  "auth/register": ["POST"],
  "auth/login": ["POST"],
  "auth/logout": ["POST"],
  "auth/forgot-password": ["POST"],
  "auth/reset-password": ["POST"],
  "auth/request-verify-token": ["POST"],
  "auth/verify": ["POST"],
  "auth/google/authorize": ["GET"],
  "users/me": ["GET"],
  "me/collection": ["GET", "POST"],
  "me/collection/import": ["POST"],
  "me/filters": ["GET", "POST"],
  recommend: ["POST"],
};

export async function accountProxy(request: Request, path: string) {
  const methods =
    allowed[path] ||
    (/^me\/collection\/\d+$/.test(path)
      ? ["PATCH", "DELETE"]
      : /^me\/filters\/[0-9a-f-]{36}$/.test(path)
        ? ["DELETE"]
        : []);
  if (!methods.includes(request.method))
    return Response.json({ detail: "Not found" }, { status: 404 });
  if (request.method !== "GET") {
    const origin = request.headers.get("origin");
    const target = new URL(request.url);
    // Check the browser's origin before forwarding a credentialed mutation.
    let valid = false;
    try {
      valid =
        !!origin &&
        new URL(origin).host === request.headers.get("host") &&
        new URL(origin).protocol === target.protocol;
    } catch {
      /* Invalid origins are rejected. */
    }
    if (!valid)
      return Response.json(
        { detail: "Invalid request origin" },
        { status: 403 },
      );
  }
  try {
    const headers = new Headers();
    for (const name of ["content-type", "x-csrf-token"]) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    const cookies = (request.headers.get("cookie") || "")
      .split(";")
      .filter((part) =>
        /^\s*fragrance_(session|csrf|oauth_state|oauth_web)=/.test(part),
      );
    if (cookies.length) headers.set("cookie", cookies.join(";"));
    const query = path === "auth/google/authorize" ? "?web=true" : "";
    const upstream = await fetch(`${base}/${path}${query}`, {
      method: request.method,
      headers,
      cache: "no-store",
      redirect: "manual",
      body: request.method === "GET" ? undefined : await request.text(),
      signal: AbortSignal.timeout(30_000),
    });
    const output = new Headers({ "Cache-Control": "no-store" });
    const contentType = upstream.headers.get("content-type");
    if (contentType) output.set("content-type", contentType);
    for (const cookie of upstream.headers.getSetCookie())
      output.append("set-cookie", cookie);
    return new Response(
      upstream.status === 204 ? null : await upstream.text(),
      { status: upstream.status, headers: output },
    );
  } catch {
    return Response.json(
      { detail: "Account service unavailable. Please try again." },
      { status: 503 },
    );
  }
}
