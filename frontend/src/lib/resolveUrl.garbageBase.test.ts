/**
 * getAbsoluteUrl with an unparseable backend base: the try/catch fallback
 * must still produce a usable origin-joined URL instead of throwing.
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('./api', () => ({
    API_BASE: 'http://exa mple.com',
}));

import { getAbsoluteUrl } from './resolveUrl';

describe('getAbsoluteUrl with garbage API_BASE', () => {
    it('falls back to origin join instead of throwing', () => {
        expect(getAbsoluteUrl('/stream/1'))
            .toBe(`${window.location.origin}/stream/1`);
    });
});
