/**
 * Post-build step: precompress every compressible asset in the Vite outDir
 * (../backend/app/static), so the backend can serve a sibling file instead of
 * compressing on every request.
 *
 * Both encodings are emitted:
 *   file.br  brotli q11 — preferred, ~30% smaller than gzip
 *   file.gz  gzip level 9 — fallback for clients without `br`
 *
 * Measured on this repo's assets:
 *   movi-player 12.2MB -> 2.55MB br (3.65MB gz)   ~20s build cost
 *   app bundle  385KB  -> 0.10MB br (0.11MB gz)
 *
 * serve_spa picks br when the client sends it, gz otherwise, plain last.
 * Dependency-free (node zlib).
 */
import { brotliCompressSync, gzipSync, constants } from 'node:zlib';
import { readdirSync, statSync, readFileSync, writeFileSync } from 'node:fs';
import { join, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

// fileURLToPath, not URL.pathname: on Windows the latter yields "/C:/..." and
// joining it produces "C:\C:\...". The build must work on a dev machine too.
const OUT_DIR = fileURLToPath(new URL('../../backend/app/static/', import.meta.url));

const COMPRESSIBLE = new Set(['.js', '.css', '.html', '.svg', '.json', '.webmanifest', '.ico', '.txt']);

// Skip the siblings a previous run wrote, so a rebuild doesn't compress
// "app.js.gz.gz". Vite's emptyOutDir is false here, so they do persist.
const ENCODING_SUFFIXES = ['.gz', '.br'];

function walk(dir) {
  let out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out = out.concat(walk(full));
    else out.push(full);
  }
  return out;
}

let count = 0, rawTotal = 0, gzTotal = 0, brTotal = 0, brotliMs = 0;
for (const file of walk(OUT_DIR)) {
  if (!COMPRESSIBLE.has(extname(file))) continue;
  if (ENCODING_SUFFIXES.some((s) => file.endsWith(s))) continue;
  const data = readFileSync(file);
  if (data.length < 1024) continue; // not worth it, matches backend minimum_size

  const gz = gzipSync(data, { level: 9 });
  if (gz.length >= data.length) continue;
  writeFileSync(file + '.gz', gz);

  const t0 = Date.now();
  const br = brotliCompressSync(data, {
    params: {
      [constants.BROTLI_PARAM_QUALITY]: 11,
      [constants.BROTLI_PARAM_LGWIN]: 24,
      [constants.BROTLI_PARAM_SIZE_HINT]: data.length,
    },
  });
  brotliMs += Date.now() - t0;
  // Keep whichever is smaller; brotli normally wins but tiny inputs can tie.
  if (br.length < gz.length) writeFileSync(file + '.br', br);

  count++;
  rawTotal += data.length;
  gzTotal += gz.length;
  brTotal += Math.min(br.length, gz.length);
}

const mb = (n) => (n / 1048576).toFixed(2);
console.log(
  `compress-assets: ${count} file(s), ${mb(rawTotal)} MB raw -> ` +
    `${mb(brTotal)} MB brotli / ${mb(gzTotal)} MB gzip on the wire ` +
    `(${Math.round(brotliMs / 1000)}s brotli)`
);
