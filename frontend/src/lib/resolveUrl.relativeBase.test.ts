/**
 * getAbsoluteUrl with a relative backend base (same-origin serving):
 * joins against the page origin, keeping the base path prefix.
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('./api', () => ({
    API_BASE: '/api',
}));

import { getAbsoluteUrl } from './resolveUrl';

describe('getAbsoluteUrl with relative API_BASE', () => {
    it('joins paths onto the page origin plus base prefix', () => {
        expect(getAbsoluteUrl('/stream/1'))
            .toBe(`${window.location.origin}/api/stream/1`);
    });

    it('passes absolute URLs through untouched', () => {
        expect(getAbsoluteUrl('https://cdn.example/x.mp4'))
            .toBe('https://cdn.example/x.mp4');
    });
});
