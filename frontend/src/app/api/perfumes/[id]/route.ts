import { backend } from "@/lib/backend";
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!/^\d+$/.test(id))
    return Response.json({ detail: "Invalid fragrance ID." }, { status: 400 });
  return backend(`/perfume/${id}`);
}
