# GramJS patch required for browser builds of session tools

`serializeBytes()` rejected native Uint8Array values produced by the app's
Uint8Array patch (`instanceof Buffer` fails across implementations), which
broke the 2FA SRP step with: "Bytes or str expected, not ...".

Fix: coerce any ArrayBuffer view into the bundle's Buffer before the checks.

Apply after `bun install`, before `bun vite build`:
    cp patches/generationHelpers.patched.js node_modules/telegram/tl/generationHelpers.js

Verified working end-to-end (phone → code → 2FA) on aaruvi.space/telegram-tools.
