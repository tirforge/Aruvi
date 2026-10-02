/**
 * Relative API_BASE coverage: when the app is served same-origin with a
 * relative backend base (e.g. `/api`), the origin guard must resolve it
 * against the page origin instead of throwing and dropping the token.
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('./api', () => ({
    API_BASE: '/api',
}));

import { isOwnBackendUrl, withToken } from './tokenGuard';

describe('isOwnBackendUrl with relative API_BASE', () => {
    it('accepts same-origin stream URLs resolved against the page origin', () => {
        expect(isOwnBackendUrl(`${window.location.origin}/api/stream/1`)).toBe(true);
    });

    it('rejects foreign origins even with a relative base', () => {
        expect(isOwnBackendUrl('https://evil.example/x.mp4')).toBe(false);
    });
});

describe('withToken with relative API_BASE', () => {
    it('appends the token to same-origin stream URLs', () => {
        expect(withToken(`${window.location.origin}/api/stream/1`, 'tok'))
            .toBe(`${window.location.origin}/api/stream/1?token=tok`);
    });
});
