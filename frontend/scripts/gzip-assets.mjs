/**
 * Post-build step: gzip every compressible asset in the Vite outDir
 * (../backend/app/static). The backend's serve_spa prefers `file.gz` when
 * the client sends Accept-Encoding: gzip — no runtime compression cost, and
 * the SPA bundle (385KB -> ~116KB) + vendored player (11MB -> ~3MB) ship
 * small on the wire. Dependency-free (node zlib).
 */
import { gzipSync } from 'node:zlib';
import { readdirSync, statSync, readFileSync, writeFileSync } from 'node:fs';
import { join, extname } from 'node:path';

const OUT_DIR = new URL('../../backend/app/static/', import.meta.url).pathname;

const COMPRESSIBLE = new Set(['.js', '.css', '.html', '.svg', '.json', '.webmanifest', '.ico', '.txt']);

function walk(dir) {
  let out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out = out.concat(walk(full));
    else out.push(full);
  }
  return out;
}

let count = 0, savedBefore = 0, savedAfter = 0;
for (const file of walk(OUT_DIR)) {
  if (!COMPRESSIBLE.has(extname(file))) continue;
  const data = readFileSync(file);
  if (data.length < 1024) continue; // not worth it, matches backend minimum_size
  const gz = gzipSync(data, { level: 9 });
  if (gz.length >= data.length) continue;
  writeFileSync(file + '.gz', gz);
  count++;
  savedBefore += data.length;
  savedAfter += gz.length;
}
console.log(
  `gzip-assets: ${count} file(s), ${(savedBefore / 1048576).toFixed(2)} MB -> ${(savedAfter / 1048576).toFixed(2)} MB on the wire`
);
