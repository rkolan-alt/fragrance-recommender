import { backend } from "@/lib/backend";
export async function GET(request: Request) {
  const q = new URL(request.url).searchParams.get("q") || "";
  return backend(`/search?${new URLSearchParams({ q, limit: "10" })}`);
}
