import { useState, useEffect, useRef } from 'react';
import { useAccessToken } from '../lib/api';

interface AuthImageProps {
    src: string;
    alt: string;
    className?: string;
}

const getAbsoluteUrl = (url: string) => {
    if (!url) return '';
    if (url.startsWith('http')) return url;
    return `${window.location.origin}${url}`;
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

        let cancelled = false;

        const loadImage = (authToken: string) =>
            fetch(url, {
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
            if (!cancelled && freshToken && freshToken !== token && err instanceof Error && err.message === 'Auth failed') {
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
            if (!cancelled) setError(true);
        });

        return () => {
            cancelled = true;
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
