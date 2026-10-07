/**
 * getAbsoluteUrl with an absolute backend base carrying a path prefix.
 * The trailing slash on the prefix must not double up in the output.
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('./api', () => ({
    API_BASE: 'http://backend.test:8000/api/',
}));

import { getAbsoluteUrl } from './resolveUrl';

describe('getAbsoluteUrl with absolute API_BASE', () => {
    it('returns empty for empty input', () => {
        expect(getAbsoluteUrl('')).toBe('');
    });

    it('passes absolute URLs through untouched', () => {
        expect(getAbsoluteUrl('https://cdn.example/x.mp4'))
            .toBe('https://cdn.example/x.mp4');
    });

    it('joins root-relative paths onto the base prefix', () => {
        expect(getAbsoluteUrl('/stream/1'))
            .toBe('http://backend.test:8000/api/stream/1');
    });

    it('adds the missing leading slash to bare paths', () => {
        expect(getAbsoluteUrl('stream/1'))
            .toBe('http://backend.test:8000/api/stream/1');
    });
});
