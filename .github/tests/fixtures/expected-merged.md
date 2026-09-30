## `backend/app/auth.py:42` (sources: opencode, rabbit, rabbit-inline, sonar)

---

### via opencode
## Review

`backend/app/auth.py:42` JWT secret falls back to a hardcoded default when env is unset. ```diff
--- a/backend/app/auth.py
+++ b/backend/app/auth.py
@@
-SECRET = os.getenv("JWT_SECRET", "changeme")
+SECRET = os.getenv("JWT_SECRET")
```

---

### via rabbit
backend/app/auth.py:42 — hardcoded fallback secret `changeme` is a critical auth bypass; require the env var.

---

### via rabbit-inline
`backend/app/auth.py:42` Same hardcoded default — inline confirmation with exact line.

---

### via sonar
[CRITICAL] backend/app/auth.py:42 python:S6437 — Change this hard-coded secret.

---

## `frontend/src/api.ts:?` (sources: sonar)

---

### via sonar
[MAJOR] frontend/src/api.ts:? typescript:S- — Missing error boundary on fetch.

---

## General (no file:line)

---

### via opencode
General note: consider rate-limiting the login route.
