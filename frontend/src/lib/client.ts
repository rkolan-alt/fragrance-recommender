export async function request<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: "omit",
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) {
    const message =
      typeof data.detail === "string"
        ? data.detail
        : "We couldn’t complete that request. Check your collection and try again.";
    throw new Error(message);
  }
  return data as T;
}

export function amazonUrl(url: string | undefined) {
  try {
    const parsed = new URL(url || "");
    return parsed.protocol === "https:" &&
      !parsed.username &&
      !parsed.password &&
      (parsed.hostname === "amazon.com" ||
        parsed.hostname.endsWith(".amazon.com"))
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}
