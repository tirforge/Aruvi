/**
 * Resolve a stream URL to absolute form against the backend base.
 * Extracted from MediaPlayer's closure for unit coverage (Sonar new-code
 * gate) — logic byte-identical to the in-component version.
 */
import { API_BASE } from './api';

/** Absolute URLs pass through; relative ones join the backend base prefix. */
export function getAbsoluteUrl(url: string): string {
    if (!url) return '';
    if (url.startsWith('http')) return url;
    try {
        const backendBase = new URL(API_BASE || window.location.origin, window.location.origin);
        let prefix = '';
        if (API_BASE) {
            let rawPath = backendBase.pathname;
            while (rawPath.length > 1 && rawPath.endsWith('/')) {
                rawPath = rawPath.slice(0, -1);
            }
            prefix = rawPath === '/' ? '' : rawPath;
        }
        const path = url.startsWith('/') ? url : `/${url}`;
        return new URL(`${prefix}${path}`, backendBase.origin).href;
    } catch {
        const path = url.startsWith('/') ? url : `/${url}`;
        return `${window.location.origin}${path}`;
    }
}
