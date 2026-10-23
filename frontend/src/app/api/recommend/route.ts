import { backend } from "@/lib/backend";
export async function POST(request: Request) {
  try {
    const body = await request.json();
    return backend("/recommend", {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch {
    return Response.json(
      { detail: "Please provide a valid collection." },
      { status: 400 },
    );
  }
}
