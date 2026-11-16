// CI / first run without the pipeline: copy test fixtures to public/data if no data exists.
import { cpSync, existsSync } from "node:fs";

if (existsSync("public/data/index.json")) {
  console.log("public/data already has data, nothing copied");
} else {
  cpSync("test/fixtures", "public/data", { recursive: true });
  console.log("copied test/fixtures -> public/data");
}
