/**
 * Post-build step: gzip every compressible asset in the Vite outDir
 * (../backend/app/static). The backend's serve_spa prefers `file.gz` when
 * the client sends Accept-Encoding: gzip — no runtime compression cost, and
 * the SPA bundle (385KB -> ~116KB) + vendored player (11MB -> ~3MB) ship
 * small on the wire. Dependency-free (node zlib).
 */
import { gzipSync } from 'node:zlib';
import { readdirSync, statSync, readFileSync, writeFileSync, unlinkSync, existsSync } from 'node:fs';
import { join, extname } from 'node:path';

const OUT_DIR = new URL('../../backend/app/static/', import.meta.url).pathname;

const COMPRESSIBLE = new Set(['.js', '.css', '.html', '.svg', '.json', '.webmanifest', '.ico', '.txt']);

function walk(dir) {
  let out = [];
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    // Out dir missing (e.g. build wrote elsewhere) — nothing to compress.
    return out;
  }
  for (const entry of entries) {
    const full = join(dir, entry);
    let st;
    try {
      st = statSync(full);
    } catch {
      // Dangling symlink or unreadable entry — skip instead of crashing postbuild.
      continue;
    }
    if (st.isDirectory()) out = out.concat(walk(full));
    else out.push(full);
  }
  return out;
}

// The backend prefers a stale `file.gz` over the fresh `file` when both
// exist — so whenever a file is skipped (too small, incompressible), any
// leftover `.gz` from an earlier build must go or clients get stale bytes.
function dropStaleGz(file) {
  try {
    if (existsSync(file + '.gz')) unlinkSync(file + '.gz');
  } catch {
    // Best effort: a leftover .gz is harmless next run, a crash is not.
  }
}

let count = 0, savedBefore = 0, savedAfter = 0;
for (const file of walk(OUT_DIR)) {
  if (!COMPRESSIBLE.has(extname(file))) continue;
  const data = readFileSync(file);
  if (data.length < 1024) { dropStaleGz(file); continue; } // not worth it, matches backend minimum_size
  const gz = gzipSync(data, { level: 9 });
  if (gz.length >= data.length) { dropStaleGz(file); continue; }
  writeFileSync(file + '.gz', gz);
  count++;
  savedBefore += data.length;
  savedAfter += gz.length;
}
console.log(
  `gzip-assets: ${count} file(s), ${(savedBefore / 1048576).toFixed(2)} MB -> ${(savedAfter / 1048576).toFixed(2)} MB on the wire`
);
