// Explicit public origin wins behind HTTPS proxies. Forwarded host/protocol
// headers are deliberately not accepted as an origin policy from the client.
export function browserOrigin(
  requestUrl: string,
  host: string | null,
  configured?: string,
) {
  const local = new URL(requestUrl);
  const target = new URL(
    configured || `${local.protocol}//${host || local.host}`,
  );
  if (
    target.username ||
    target.password ||
    !["http:", "https:"].includes(target.protocol)
  )
    throw new Error("Invalid public origin");
  return target.origin;
}
export function validMutationOrigin(
  origin: string | null,
  requestUrl: string,
  host: string | null,
  configured?: string,
) {
  try {
    return (
      origin !== null && origin === browserOrigin(requestUrl, host, configured)
    );
  } catch {
    return false;
  }
}
export function returnLocation(
  location: string,
  requestUrl: string,
  host: string | null,
  configured?: string,
) {
  const expected = browserOrigin(requestUrl, host, configured);
  const target = new URL(location, expected);
  return target.origin === expected && !target.username && !target.password
    ? target.href
    : null;
}
