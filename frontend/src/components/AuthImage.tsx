import { useState, useEffect, useRef } from 'react';
import { API_BASE, useAccessToken } from '../lib/api';

interface AuthImageProps {
    src: string;
    alt: string;
    className?: string;
}

const getAbsoluteUrl = (url: string) => {
    if (!url) return '';
    // Absolute-URL check must include the scheme separator: a bare
    // startsWith('http') also matched relative strings like 'httpfoo',
    // which then skipped the origin join below and fetched a wrong path.
    if (/^https?:\/\//i.test(url)) return url;
    // Respect split frontend/backend deploys (__BACKEND_URL__) and tolerate
    // relative paths missing the leading slash (which naive concatenation
    // mangles into https://hostapi/...). Falls back to origin-joined.
    try {
        return new URL(url, API_BASE || window.location.origin).href;
    } catch {
        return `${window.location.origin}/${url.replace(/^\/+/, '')}`;
    }
};

export default function AuthImage({ src, alt, className }: AuthImageProps) {
    const [blobUrl, setBlobUrl] = useState<string | null>(null);
    const [error, setError] = useState(false);
    const blobUrlRef = useRef<string | null>(null);
    const imgRef = useRef<HTMLDivElement>(null);
    // Lazy: only fetch (an authorized request + blob) once the card scrolls
    // near the viewport. Infinite scroll mounts every card immediately —
    // without this, a 500-file library fires 500 thumbnail fetches at once.
    const [visible, setVisible] = useState(false);
    useEffect(() => {
        const el = imgRef.current;
        if (!el || visible) return;
        const io = new IntersectionObserver(
            (entries) => {
                if (entries.some((e) => e.isIntersecting)) {
                    setVisible(true);
                    io.disconnect();
                }
            },
            { rootMargin: '200px' }
        );
        io.observe(el);
        return () => io.disconnect();
    }, [visible]);

    // Reactive token: when it's rotated mid-session (401 refresh, another tab),
    // this changes and re-runs the fetch below with the fresh token — a plain
    // localStorage read at mount would leave the thumbnail stuck 401ing forever.
    const accessToken = useAccessToken();

    const MAX_THUMBNAIL_BYTES = 5 * 1024 * 1024; // 5MB limit

    useEffect(() => {
        blobUrlRef.current = null;
        setBlobUrl(null);
        setError(false);

        const token = accessToken;
        if (!token || !src || !visible) {
            return;
        }

        const url = getAbsoluteUrl(src);

        // Bearer-leak guard: the Authorization header must only ever go to
        // our own backend (API_BASE or same origin). If `src` ever resolves
        // to a foreign origin, refuse instead of sending the token there.
        let fetchUrl = url;
        try {
            const ownOrigins = new Set([
                new URL(API_BASE || window.location.origin, window.location.origin).origin,
                window.location.origin,
            ]);
            const parsed = new URL(url, window.location.origin);
            if (!ownOrigins.has(parsed.origin)) {
                setError(true);
                return;
            }
            fetchUrl = parsed.href;
        } catch {
            setError(true);
            return;
        }

        let cancelled = false;
        // Abort the in-flight download on unmount/src change/token rotation.
        // The old `cancelled` flag only skipped setState — the fetch kept
        // downloading, so fast-scrolling a big library left dozens of orphaned
        // thumbnail downloads hammering the backend.
        const controller = new AbortController();
        const signal = controller.signal;

        const loadImage = (authToken: string) =>
            fetch(fetchUrl, {
                signal,
                headers: { 'Authorization': `Bearer ${authToken}` }
            })
            .then((res) => {
                if (!res.ok) throw new Error('Auth failed');
                const contentLength = res.headers.get('content-length');
                if (contentLength && parseInt(contentLength) > MAX_THUMBNAIL_BYTES) {
                    throw new Error('Thumbnail too large');
                }
                return res.blob();
            });

        loadImage(token)
        .catch((err) => {
            // Token may have expired mid-session - retry once with whatever token
            // is currently in storage (another tab may have refreshed it).
            const freshToken = localStorage.getItem('access_token');
            if (!cancelled && !signal.aborted && freshToken && freshToken !== token && err instanceof Error && err.message === 'Auth failed') {
                return loadImage(freshToken);
            }
            throw err;
        })
        .then((blob) => {
            if (cancelled) return;
            if (blob.size > MAX_THUMBNAIL_BYTES) {
                throw new Error('Thumbnail too large');
            }
            const url = URL.createObjectURL(blob);
            blobUrlRef.current = url;
            setBlobUrl(url);
        })
        .catch(() => {
            // Aborts are intentional, not errors — don't blank the thumbnail.
            if (!cancelled && !signal.aborted) setError(true);
        });

        return () => {
            cancelled = true;
            controller.abort();
            if (blobUrlRef.current) {
                URL.revokeObjectURL(blobUrlRef.current);
                blobUrlRef.current = null;
            }
        };
    }, [src, accessToken, visible]);

    if (error) return null;

    if (!blobUrl) return <div ref={imgRef} className={className} aria-hidden="true" />;

    return <img src={blobUrl} alt={alt} className={className} />;
}
