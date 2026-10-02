/**
 * Token guard tests: the account JWT must only ever be appended to our
 * own backend origin. A regression here exfiltrates the token to third
 * parties (their server logs / Referer).
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('./api', () => ({
    API_BASE: 'http://backend.test:8000',
}));

import { isOwnBackendUrl, withToken } from './tokenGuard';

describe('isOwnBackendUrl', () => {
    it('accepts the backend origin itself', () => {
        expect(isOwnBackendUrl('http://backend.test:8000')).toBe(true);
    });

    it('accepts same-origin stream URLs with paths and queries', () => {
        expect(isOwnBackendUrl('http://backend.test:8000/stream/1?token=x')).toBe(true);
    });

    it('rejects foreign https origins', () => {
        expect(isOwnBackendUrl('https://evil.example/x.mp4')).toBe(false);
    });

    it('rejects same-host different-port URLs', () => {
        expect(isOwnBackendUrl('http://backend.test:9000/stream/1')).toBe(false);
    });

    it('rejects relative and garbage input (never crash)', () => {
        expect(isOwnBackendUrl('/stream/1')).toBe(false);
        expect(isOwnBackendUrl('not a url')).toBe(false);
        expect(isOwnBackendUrl('')).toBe(false);
    });
});

describe('withToken', () => {
    it('appends ?token= for own-backend URLs', () => {
        expect(withToken('http://backend.test:8000/stream/1', 'tok'))
            .toBe('http://backend.test:8000/stream/1?token=tok');
    });

    it('appends &token= when a query string already exists', () => {
        expect(withToken('http://backend.test:8000/stream/1?dl=1', 'tok'))
            .toBe('http://backend.test:8000/stream/1?dl=1&token=tok');
    });

    it('leaves foreign URLs untouched even with a token', () => {
        expect(withToken('https://evil.example/x.mp4', 'tok'))
            .toBe('https://evil.example/x.mp4');
    });

    it('leaves every URL untouched when the token is null', () => {
        expect(withToken('http://backend.test:8000/stream/1', null))
            .toBe('http://backend.test:8000/stream/1');
        expect(withToken('https://evil.example/x.mp4', null))
            .toBe('https://evil.example/x.mp4');
    });
});
