/**
 * getAbsoluteUrl with an empty backend base (pure same-origin mode):
 * no prefix, plain origin join. Also covers the empty-input early return.
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('./api', () => ({
    API_BASE: '',
}));

import { getAbsoluteUrl } from './resolveUrl';

describe('getAbsoluteUrl with empty API_BASE', () => {
    it('returns empty for empty input', () => {
        expect(getAbsoluteUrl('')).toBe('');
    });

    it('joins paths directly onto the page origin', () => {
        expect(getAbsoluteUrl('/stream/1'))
            .toBe(`${window.location.origin}/stream/1`);
    });
});
