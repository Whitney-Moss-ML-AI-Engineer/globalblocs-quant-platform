// Copies the shared dashboard build (frontend/out) into the phone app's web folder.
const fs = require("fs"), path = require("path");
const src = path.join(__dirname, "..", "..", "frontend", "out");
const dst = path.join(__dirname, "..", "www");
if (!fs.existsSync(path.join(src, "index.html"))) {
  console.error("Dashboard not built. Run: cd frontend && npm ci && npm run build"); process.exit(1);
}
fs.rmSync(dst, { recursive: true, force: true });
fs.cpSync(src, dst, { recursive: true });
console.log(`Copied dashboard to ${dst}`);
