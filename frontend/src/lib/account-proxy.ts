import "server-only";
import { validMutationOrigin, returnLocation } from "./proxy-policy";

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
  "auth/google/associate/authorize": ["GET"],
  "auth/google/callback": ["GET"],
  "auth/google/associate/callback": ["GET"],
  "users/me": ["GET"],
  "me/oauth": ["GET"],
  "me/password": ["POST"],
  me: ["DELETE"],
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
    // Check the browser's origin before forwarding a credentialed mutation.
    const valid = validMutationOrigin(
      origin,
      request.url,
      request.headers.get("host"),
      process.env.FRAGRANCE_PUBLIC_ORIGIN,
    );
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
    const callback =
      path === "auth/google/callback" ||
      path === "auth/google/associate/callback";
    const query = callback
      ? new URL(request.url).search
      : path.endsWith("/authorize")
        ? "?web=true"
        : "";
    const upstream = await fetch(`${base}/${path}${query}`, {
      method: request.method,
      headers,
      cache: "no-store",
      redirect: "manual",
      body: request.method === "GET" ? undefined : await request.text(),
      signal: AbortSignal.timeout(30_000),
    });
    const output = new Headers({ "Cache-Control": "no-store" });
    const location = upstream.headers.get("location");
    if (location) {
      const destination = returnLocation(
        location,
        request.url,
        request.headers.get("host"),
        process.env.FRAGRANCE_PUBLIC_ORIGIN,
      );
      if (!callback || !destination)
        return Response.json(
          { detail: "Invalid sign-in return address" },
          { status: 502 },
        );
      output.set("location", destination);
    }
    const requestId = upstream.headers.get("x-request-id");
    if (requestId) output.set("x-request-id", requestId);
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
