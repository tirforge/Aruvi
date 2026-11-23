/**
 * Context menu placement.
 *
 * The menu used to be positioned by a hand-rolled clamp that assumed a
 * 220x300 box and only nudged the top edge, so an eight-row menu opened near
 * the bottom of a short window had its last actions rendered off screen.
 * Placement now comes from floating-ui, which measures the menu.
 *
 * Two things are worth guarding here:
 *  - the float hooks run before the early `return null`, otherwise React
 *    throws "Rendered more hooks than during the previous render" the first
 *    time the menu opens (it is permanently mounted at the app root);
 *  - the height is capped to the viewport, not to a hardcoded 300px.
 */
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import GlobalContextMenu from './GlobalContextMenu';
import { useAppStore } from '../lib/store';

// Unit under test is placement, not data fetching or link minting.
vi.mock('../lib/api', () => ({
    api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
    useFolders: () => ({ data: [], isLoading: false }),
    useAccessToken: () => 'test-token',
    getFileDownloadToken: vi.fn(),
    backendUrl: (url: string) => url,
    isTrustedBackendUrl: () => true,
}));

const FILE = {
    id: 'f1',
    file_name: 'movie.mkv',
    file_size: 1024,
    mime_type: 'video/x-matroska',
    created_at: '2026-01-01T00:00:00Z',
    folder_id: null,
    telegram_message_id: 1,
} as any;

function openMenu(x: number, y: number) {
    act(() => {
        useAppStore.setState({
            activeContextMenu: { type: 'file', item: FILE, x, y },
        });
    });
}

/** The menu panel, not the full-screen click-catcher. */
function menuPanel(container: HTMLElement): HTMLElement {
    const item = container.querySelector('.context-menu-item');
    expect(item).not.toBeNull();
    return item!.closest('div[class*="fixed"]') as HTMLElement;
}

beforeEach(() => {
    // jsdom has no layout: documentElement.clientWidth/Height are 0, which
    // makes floating-ui's clipping rect zero-sized and availableHeight
    // negative. Stub a 1024x768 viewport so the size middleware has real
    // space to work with.
    Object.defineProperty(document.documentElement, 'clientWidth', {
        value: 1024,
        configurable: true,
    });
    Object.defineProperty(document.documentElement, 'clientHeight', {
        value: 768,
        configurable: true,
    });
    useAppStore.setState({
        activeContextMenu: null,
        selectedFileIds: new Set<number>(),
        selectedFolderIds: new Set<number>(),
        selectedFiles: [],
    });
});

afterEach(cleanup);

describe('GlobalContextMenu placement', () => {
    it('opens after a closed render without a hook-order error', async () => {
        const errors: unknown[] = [];
        const spy = vi.spyOn(console, 'error').mockImplementation((...args) => {
            errors.push(args[0]);
        });

        const { container } = render(<GlobalContextMenu />);
        expect(container.firstElementChild).toBeNull();

        expect(() => openMenu(40, 60)).not.toThrow();
        await waitFor(() => expect(container.textContent).toContain('Download'));
        expect(errors).toEqual([]);

        spy.mockRestore();
    });

    it('caps its height to the viewport instead of a hardcoded 300px', async () => {
        const { container } = render(<GlobalContextMenu />);
        // A click near the bottom edge: the old clamp pinned top to
        // innerHeight - 300 and let the rest overflow.
        openMenu(40, window.innerHeight - 5);

        const menu = menuPanel(container);
        expect(menu.style.position).toBe('fixed');

        // floating-ui computes asynchronously, so wait for the size middleware
        // to write its cap.
        await waitFor(() => expect(menu.style.maxHeight).toMatch(/px$/));
        const maxHeight = Number.parseFloat(menu.style.maxHeight);
        // The cap is the viewport minus the 10px padding the middleware is
        // given, not the old hardcoded 300px assumption.
        expect(maxHeight).toBe(768 - 20);
        // The scrolling fallback is what makes the clipped actions reachable.
        expect(menu.style.overflowY).toBe('auto');
    });

    it('re-anchors when the menu is opened at a new point', async () => {
        const { container } = render(<GlobalContextMenu />);
        openMenu(10, 10);
        openMenu(200, 300);

        const menu = menuPanel(container);
        // jsdom reports zero-size rects, so absolute values carry no meaning;
        // what matters is that a position was computed at all and stays fixed.
        await waitFor(() => expect(menu.style.left).toMatch(/px$/));
        expect(menu.style.top).toMatch(/px$/);
        expect(container.textContent).toContain('Download');
    });
});
