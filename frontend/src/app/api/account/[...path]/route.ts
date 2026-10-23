import { accountProxy } from "@/lib/account-proxy";
async function handle(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  return accountProxy(request, path.join("/"));
}
export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
