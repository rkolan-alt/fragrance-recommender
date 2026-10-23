export class AccountError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
const messages: Record<string, string> = {
  LOGIN_BAD_CREDENTIALS: "Check your email and password and try again.",
  REGISTER_USER_ALREADY_EXISTS:
    "An account with this email already exists. Sign in instead.",
  RESET_PASSWORD_BAD_TOKEN:
    "This reset link has expired or was already used. Request a new one.",
  VERIFY_USER_BAD_TOKEN:
    "This verification link has expired or was already used.",
  VERIFY_USER_ALREADY_VERIFIED:
    "Your email is already verified. You can sign in.",
};
export async function accountRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") {
    const csrf = await accountRequest<{ csrf_token: string }>("auth/csrf");
    headers.set("X-CSRF-Token", csrf.csrf_token);
    if (!headers.has("Content-Type"))
      headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/account/${path}`, {
    ...init,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    const detail = data?.detail;
    const code = typeof detail === "string" ? detail : detail?.code;
    const validation = Array.isArray(detail)
      ? detail
          .map((item) => item.msg)
          .filter((message) => typeof message === "string")
          .join(" ")
      : "";
    throw new AccountError(
      messages[code] ||
        detail?.reason ||
        validation ||
        (typeof detail === "string"
          ? detail
          : "We couldn’t complete that request. Please try again."),
      response.status,
    );
  }
  return data as T;
}
