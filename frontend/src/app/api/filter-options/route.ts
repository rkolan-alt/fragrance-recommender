import { backend } from "@/lib/backend";
export async function GET() {
  return backend("/filter-options");
}
