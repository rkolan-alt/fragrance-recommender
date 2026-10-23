// Start the same standalone output used by the Cloud Run image, with its assets.
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const frontend = join(root, "frontend");
const standalone = join(frontend, ".next", "standalone");
const server = join(standalone, "server.js");
if (!existsSync(server)) {
  throw new Error("Production output is missing. Run npm run build first.");
}
mkdirSync(join(standalone, ".next"), { recursive: true });
cpSync(join(frontend, ".next", "static"), join(standalone, ".next", "static"), {
  recursive: true,
});
cpSync(join(frontend, "public"), join(standalone, "public"), { recursive: true });
process.env.HOSTNAME ||= "127.0.0.1";
await import(pathToFileURL(server).href);
