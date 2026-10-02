/**
 * Token guard: the account JWT must ONLY go to our own backend origin.
 * Appending it to a foreign stream URL would exfiltrate the token to a
 * third party (their server logs / Referer). Same-origin backend URLs
 * keep working exactly as before.
 */
import { API_BASE } from './api';

/** True when an absolute URL shares our backend's origin. */
export function isOwnBackendUrl(absoluteUrl: string): boolean {
    try {
        const urlOrigin = new URL(absoluteUrl).origin;
        const backendOrigin = new URL(API_BASE || window.location.origin).origin;
        return urlOrigin === backendOrigin;
    } catch {
        return false;
    }
}

/** Append the access token only for own-backend URLs; otherwise unchanged. */
export function withToken(base: string, token: string | null): string {
    if (!token || !isOwnBackendUrl(base)) return base;
    const sep = base.includes('?') ? '&' : '?';
    return `${base}${sep}token=${token}`;
}
