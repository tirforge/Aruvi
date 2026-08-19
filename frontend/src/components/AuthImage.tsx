import { useState, useEffect, useRef } from 'react';
import { useAccessToken } from '../lib/api';

interface AuthImageProps {
    src: string;
    alt: string;
    className?: string;
}

export default function AuthImage({ src, alt, className }: AuthImageProps) {
    const [blobUrl, setBlobUrl] = useState<string | null>(null);
    const [error, setError] = useState(false);
    const blobUrlRef = useRef<string | null>(null);

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
        if (!token || !src) {
            setError(true);
            return;
        }

        let cancelled = false;

        const loadImage = (authToken: string) =>
            fetch(src, {
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
    }, [src, accessToken]);

    if (error || !blobUrl) return null;

    return <img src={blobUrl} alt={alt} className={className} />;
}
