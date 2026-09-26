import { useEffect, useRef } from 'react';

/**
 * useFocusReturn - captures the focused element on mount and restores focus
 * to it on unmount. For conditionally-mounted overlays (modals, pickers):
 * without this, closing the overlay drops focus to <body> and keyboard
 * users lose their place (same bug class as the player overlay buttons).
 * Restoring to a detached node is a harmless no-op, so item-deleted-then-
 * closed flows are safe.
 */
export function useFocusReturn() {
    const openerRef = useRef<HTMLElement | null>(null);
    useEffect(() => {
        openerRef.current = document.activeElement as HTMLElement | null;
        return () => {
            try { openerRef.current?.focus?.({ preventScroll: true }); } catch { /* noop */ }
        };
    }, []);
}
