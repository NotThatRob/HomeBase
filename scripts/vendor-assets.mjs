import { copyFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const assets = [
  ["node_modules/htmx.org/dist/htmx.min.js", "app/static/vendor/htmx.min.js"],
  ["node_modules/chart.js/dist/chart.umd.js", "app/static/vendor/chart.umd.js"]
];

for (const [_source, target] of assets) {
  mkdirSync(dirname(target), { recursive: true });
}

for (const [source, target] of assets) {
  copyFileSync(source, target);
}
