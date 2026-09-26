import { useEffect, useRef } from 'react';

/**
 * useFocusReturn - captures the focused element on mount and restores focus
 * to it on unmount. For conditionally-mounted overlays (modals, pickers):
 * without this, closing the overlay drops focus to <body> and keyboard
 * users lose their place (same bug class as the player overlay buttons).
 * Restoring to a detached node is a harmless no-op, so item-deleted-then-
 * closed flows are safe.
 *
 * Opener capture prefers a last-interaction tracker over bare
 * `document.activeElement`: click-opened overlays often mount in the same
 * tick while focus still sits on <body>, so activeElement alone snapshots
 * nothing useful. The tracker records the last pointer/keyboard/focus
 * target app-wide (installed once); the hook falls back to activeElement.
 */
let lastInteract: HTMLElement | null = null;
let trackerInstalled = false;

function installTracker() {
    if (trackerInstalled) return;
    trackerInstalled = true;
    const snap = (e: Event) => {
        const t = e.target as HTMLElement | null;
        if (t && t !== document.body && document.contains(t)) lastInteract = t;
    };
    window.addEventListener('pointerdown', snap, true);
    window.addEventListener('keydown', snap, true);
    window.addEventListener('focusin', snap, true);
}

export function useFocusReturn() {
    const openerRef = useRef<HTMLElement | null>(null);
    useEffect(() => {
        installTracker();
        const active = document.activeElement as HTMLElement | null;
        openerRef.current =
            (active && active !== document.body && document.contains(active))
                ? active
                : (lastInteract && document.contains(lastInteract) ? lastInteract : null);
        return () => {
            try { openerRef.current?.focus?.({ preventScroll: true }); } catch { /* noop */ }
        };
    }, []);
}
