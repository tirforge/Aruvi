const LOGIN_CODE_KEY = 'teleplay_login_code';

interface StoredLoginCode {
    code: string;
    expires_at: string;
}

// Code survives page reloads so it never changes under the user mid-login.
// Expiry comes from the backend's expires_at (server code TTL); expired
// codes are discarded so a stale code is never reused.

// Backend sends naive UTC datetimes (no timezone suffix); JS would parse
// them as local time. Treat naive values as UTC to match the server clock.
export function parseExpiry(expiresAt: string): number {
    const normalized = /(Z|[+-]\d{2}:\d{2})$/i.test(expiresAt) ? expiresAt : expiresAt + 'Z';
    const time = new Date(normalized).getTime();
    return Number.isNaN(time) ? 0 : time;
}

export function getStoredLoginCode(): StoredLoginCode | null {
    try {
        const raw = localStorage.getItem(LOGIN_CODE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw) as StoredLoginCode;
        if (!parsed.code || !parsed.expires_at) return null;
        if (parseExpiry(parsed.expires_at) <= Date.now()) {
            localStorage.removeItem(LOGIN_CODE_KEY);
            return null;
        }
        return parsed;
    } catch {
        // Corrupt or unavailable storage — treat as no saved code
        return null;
    }
}

export function storeLoginCode(code: string, expiresAt: string): void {
    try {
        localStorage.setItem(LOGIN_CODE_KEY, JSON.stringify({ code, expires_at: expiresAt }));
    } catch {
        // Storage unavailable — code still works for this session
    }
}

export function clearStoredLoginCode(): void {
    try {
        localStorage.removeItem(LOGIN_CODE_KEY);
    } catch {
        // nothing to clear
    }
}
