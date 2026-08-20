import { useState } from 'react';
import { useMemo, useRef, useEffect, useCallback } from 'react';
import { X, Play, Pause, SkipBack, SkipForward, Download, ExternalLink, AlertTriangle, Copy, Music, Film, ChevronDown, ChevronUp, Subtitles, Search, Loader2 } from 'lucide-react';
import { TelegramFile, formatDuration, useUpdateProgress, useFile, getFileDownloadToken, useAccessToken, searchInternetSubtitles, fetchSubtitleContent, SubtitleCandidate } from '../lib/api';
import { useAppStore } from '../lib/store';
import AuthImage from './AuthImage';

const MOVI_PLAYER_URL = 'https://cdn.jsdelivr.net/npm/movi-player@0.3.5/dist/element.js';
let moviLoadPromise: Promise<boolean> | null = null;

// Warm the engine in the background once the page has painted, so the first
// movie the user opens mounts movi-player immediately instead of flashing the
// app's loading spinner for the ~1s it takes to fetch the 11MB module from the
// CDN. No-op after the first load (customElements.get guard + moviLoadPromise).
if (typeof window !== 'undefined') {
    const warm = () => loadMoviPlayer();
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(warm, 500);
    } else {
        window.addEventListener('load', () => setTimeout(warm, 500));
    }
}

// movi-player is the ONLY player engine: a WebCodecs + FFmpeg WASM custom
// element that decodes HEVC/H.265, AV1, H.264, AC-3, DTS and any FFmpeg
// container (MKV/MP4/TS/MOV) entirely in the browser. It ships its own
// controls, settings (quality/speed/aspect), multi-audio + subtitle menus,
// gestures, hotkeys, PiP, HDR and resume. No native <video>/<audio> fallback.
function loadMoviPlayer(): Promise<boolean> {
    if (window.customElements.get('movi-player')) return Promise.resolve(true);
    if (moviLoadPromise) return moviLoadPromise;
    moviLoadPromise = new Promise((resolve) => {
        const s = document.createElement('script');
        s.type = 'module';
        s.src = MOVI_PLAYER_URL;
        s.onload = () => resolve(true);
        s.onerror = () => resolve(false);
        document.head.appendChild(s);
    });
    return moviLoadPromise;
}

export default function MediaPlayer() {
    const { previewFile: file, setPreviewFile, isPlayerMinimized, setPlayerMinimized } = useAppStore();

    if (!file) return null;

    const closePlayer = () => {
        setPreviewFile(null);
        setPlayerMinimized(false);
    };

    return <MediaPlayerContent file={file} onClose={closePlayer} isMinimized={isPlayerMinimized} setMinimized={setPlayerMinimized} />;
}

interface MediaPlayerContentProps {
    file: TelegramFile;
    onClose: () => void;
    isMinimized: boolean;
    setMinimized: (minimized: boolean) => void;
}

function MediaPlayerContent({ file, onClose, isMinimized, setMinimized }: MediaPlayerContentProps) {
    const moviMountRef = useRef<HTMLDivElement>(null);
    const elRef = useRef<any>(null);
    const hideControlsTimeout = useRef<ReturnType<typeof setTimeout>>();
    const isMinimizedRef = useRef(isMinimized);
    useEffect(() => { isMinimizedRef.current = isMinimized; }, [isMinimized]);
    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [showControls, setShowControls] = useState(true);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [moviStatus, setMoviStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');

    // Subtitles — a list of TRACKS the user can switch between: uploaded local
    // files plus internet downloads (movi-player's subtitle menu lists every
    // track, native embedded + these external ones, and toggles them on demand).
    const [subtitleTracks, setSubtitleTracks] = useState<{ key: string; label: string; url: string }[]>([]);
    const [activeSubKey, setActiveSubKey] = useState<string | null>(null);
    const activeSubKeyRef = useRef<string | null>(null);
    useEffect(() => { activeSubKeyRef.current = activeSubKey; }, [activeSubKey]);
    const [showSubPicker, setShowSubPicker] = useState(false);
    const subtitleInputRef = useRef<HTMLInputElement>(null);
    const subtitleBlobUrlsRef = useRef<string[]>([]);

    // Internet subtitle search
    const [internetSubs, setInternetSubs] = useState<SubtitleCandidate[] | null>(null);
    const [internetLoading, setInternetLoading] = useState(false);
    const [internetError, setInternetError] = useState<string | null>(null);
    const [selectedInternet, setSelectedInternet] = useState<Set<string>>(new Set());
    const [attachingSubs, setAttachingSubs] = useState(false);

    const isVideo = file.file_type === 'video' || file.mime_type?.startsWith('video/');
    const isImage = file.file_type === 'image' || file.mime_type?.startsWith('image/');

    // Reset player state when the file changes (component instance persists across files)
    useEffect(() => {
        setIsPlaying(false);
        setCurrentTime(0);
        setDuration(0);
        setError(null);
        setSubtitleTracks([]);
        setActiveSubKey(null);
        setInternetSubs(null);
        setInternetError(null);
        setSelectedInternet(new Set());
        setIsLoading(!isImage);
    }, [file.id, isImage]);

    // Revoke subtitle blob URLs on unmount / file change
    useEffect(() => {
        return () => {
            for (const url of subtitleBlobUrlsRef.current) {
                URL.revokeObjectURL(url);
            }
            subtitleBlobUrlsRef.current = [];
        };
    }, [file.id]);

    // ponytail: minimal SRT→VTT converter, covers 99% of real SRT files
    const srtToVtt = (srt: string): string => {
        let vtt = 'WEBVTT\n\n';
        vtt += srt
            .replace(/\r\n/g, '\n')
            .replace(/(\d+)\r?\n(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})/g, (_, _id, start, end) =>
                `
${start.replace(',', '.')} --> ${end.replace(',', '.')}`
            )
            .replace(/^\n+/, '');
        return vtt;
    };

    const handleSubtitleFile = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        // MicroDVD (.sub) is not supported — the SRT→VTT converter would mangle it
        if (file.name.toLowerCase().endsWith('.sub')) return;
        const reader = new FileReader();
        reader.onload = () => {
            let text = reader.result as string;
            // Convert SRT to VTT if needed
            if (file.name.endsWith('.srt')) {
                text = srtToVtt(text);
            }
            const blob = new Blob([text], { type: 'text/vtt' });
            const url = URL.createObjectURL(blob);
            subtitleBlobUrlsRef.current.push(url);
            const label = file.name.replace(/\.[^.]+$/, '');
            const key = `upload-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
            setSubtitleTracks((prev) => [...prev, { key, label, url }]);
            setActiveSubKey(key);
            setShowSubPicker(false);
        };
        reader.readAsText(file);
    }, []);

    // Search the internet (OpenSubtitles + keyless providers) for subtitles
    const handleInternetSearch = useCallback(async () => {
        if (internetLoading) return;
        setInternetLoading(true);
        setInternetError(null);
        try {
            const res = await searchInternetSubtitles(file.id);
            setInternetSubs(res.subtitles);
        } catch (err: any) {
            setInternetError(err?.response?.data?.detail || 'Subtitle search failed');
        } finally {
            setInternetLoading(false);
        }
    }, [file.id, internetLoading]);

    // Toggle a checkmark on/off for an internet result
    const toggleInternetSelect = useCallback((key: string) => {
        setSelectedInternet((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key); else next.add(key);
            return next;
        });
    }, []);

    // Download selected internet subtitles and attach them as tracks
    const handleAttachInternet = useCallback(async () => {
        if (!internetSubs || attachingSubs) return;
        const chosen = internetSubs.filter((s) => selectedInternet.has(`${s.provider}:${s.id}`));
        if (chosen.length === 0) return;
        setAttachingSubs(true);
        try {
            const tracks = await Promise.all(
                chosen.map(async (s) => {
                    const content = await fetchSubtitleContent(file.id, s.provider, s.id, s.download_id);
                    let text = content.text;
                    if (content.format === 'srt') text = srtToVtt(text);
                    const blob = new Blob([text], { type: 'text/vtt' });
                    const url = URL.createObjectURL(blob);
                    subtitleBlobUrlsRef.current.push(url);
                    const label = s.name.length > 45 ? s.name.slice(0, 45) + '…' : s.name;
                    return { key: `${s.provider}:${s.id}`, label, url };
                }),
            );
            setSubtitleTracks((prev) => [...prev, ...tracks]);
            if (tracks.length > 0) setActiveSubKey(tracks[0].key);
            setSelectedInternet(new Set());
            setShowSubPicker(false);
        } catch (err: any) {
            setInternetError(err?.response?.data?.detail || 'Failed to attach subtitles');
        } finally {
            setAttachingSubs(false);
        }
    }, [internetSubs, selectedInternet, attachingSubs, file.id]);

    const { mutate: updateProgress } = useUpdateProgress();
    const { data: extendedFile, isError: extendedFileError } = useFile(file.id);

    // Load the movi-player engine unconditionally for video/audio (no native
    // fallback). Images render as a plain <img> — no engine needed.
    useEffect(() => {
        if (isImage) return;
        setMoviStatus('loading');
        setIsLoading(true);
        loadMoviPlayer().then((ok) => {
            setMoviStatus(ok ? 'ready' : 'error');
            if (ok) {
                setIsLoading(false);
            } else {
                setError('The playback engine failed to load. Check your connection and try again.');
            }
        });
    }, [file.id, isImage]);

    const getAbsoluteUrl = (url: string) => {
        if (!url) return '';
        if (url.startsWith('http')) return url;
        return `${window.location.origin}${url}`;
    };

    // Capture the authorized stream URL once per file so a token refresh
    // doesn't change the src and restart playback. Appends the access token
    // with the right separator: grabbed files arrive with a `?token=` download
    // link already in stream_url, so a second `?` would swallow both tokens
    // into one malformed query value and the stream comes back "not authed".
    const authorizedStreamUrl = useMemo(() => {
        const token = localStorage.getItem('access_token');
        const base = getAbsoluteUrl(file.stream_url || '');
        const sep = base.includes('?') ? '&' : '?';
        return `${base}${sep}token=${token}`;
    }, [file.id, file.stream_url]);
    // Still images don't risk restarting playback, so use the reactive token:
    // if it rotates mid-viewing, the <img> re-renders with a fresh token instead
    // of 401ing forever until the user reopens the file.
    const reactiveToken = useAccessToken();
    const imageUrl = useMemo(() => {
        if (!isImage) return authorizedStreamUrl;
        const base = getAbsoluteUrl(file.stream_url || '');
        const sep = base.includes('?') ? '&' : '?';
        return `${base}${sep}token=${reactiveToken}`;
    }, [file.stream_url, file.id, isImage, reactiveToken, authorizedStreamUrl]);
    const externalUrl = getAbsoluteUrl((extendedFile || file).public_stream_url || '') || authorizedStreamUrl;
    const vlcUrl = `vlc://${externalUrl}`;

    // If the access token rotates mid-playback (refresh interceptor), the
    // frozen authorizedStreamUrl would 401 on the next request with no way to
    // recover. Re-source the element with a fresh token only when it actually
    // changed, preserving the current playhead and play state.
    const mountedFileRef = useRef<number | null>(null);
    const prevTokenRef = useRef<string>(reactiveToken);
    useEffect(() => {
        const el = elRef.current;
        if (!el || isImage || mountedFileRef.current !== file.id) return;
        if (prevTokenRef.current === reactiveToken || !prevTokenRef.current) {
            prevTokenRef.current = reactiveToken;
            return;
        }
        prevTokenRef.current = reactiveToken;
        const wasPlaying = !el.paused;
        const prevTime = el.currentTime || 0;
        el.source({
            video: { src: authorizedStreamUrl, type: 'video/mp4' },
        });
        const restore = () => {
            try {
                if (prevTime > 0) el.currentTime = prevTime;
            } catch { /* noop */ }
            if (wasPlaying) {
                try { el.play(); } catch { /* noop */ }
            }
            el.removeEventListener('loadeddata', restore);
        };
        el.addEventListener('loadeddata', restore);
    }, [reactiveToken, authorizedStreamUrl, isImage, file.id]);

    const handleDownload = async () => {
        // Open the target tab synchronously (still inside the click gesture) so
        // browsers don't block it as a popup, then point it at the download page
        // once the token arrives. Falls back to same-tab navigation when a popup
        // was blocked (win === null).
        const win = window.open('', '_blank');
        try {
            const token = await getFileDownloadToken(file.id);
            const dlUrl = `${window.location.protocol}//${window.location.host}/api/stream/dl?id=${file.id}&token=${encodeURIComponent(token)}`;
            if (win) win.location.href = dlUrl;
            else window.location.href = dlUrl;
        } catch (err) {
            console.warn('Failed to get download token, falling back to stream URL:', err);
            if (win) win.location.href = externalUrl;
            else window.location.href = externalUrl;
        }
    };

    const resumeStart = Math.floor(extendedFile?.last_pos ?? 0);
    // Stable snapshot of the resume position: the mount effect below must read
    // the latest value without re-running (and recreating the player) every time
    // a refetched file updates last_pos — that recreation was causing a full
    // reload whenever the tab regained focus.
    const resumeStartRef = useRef(resumeStart);
    useEffect(() => { resumeStartRef.current = resumeStart; }, [resumeStart]);

    // Wait for the first successful file fetch before mounting the player so
    // `resumeStartRef` holds the latest last_pos (startat would otherwise be
    // built from a stale/zero resume point). This is state keyed on the file id
    // rather than the `extendedFile` object itself: the mount effect must re-run
    // when the FIRST fetch resolves, but must NOT re-run (and rebuild the player)
    // on later refetches, or playback would restart mid-watch.
    const [extendedReadyForFile, setExtendedReadyForFile] = useState<number | null>(null);
    useEffect(() => {
        if (extendedFile || extendedFileError) {
            setExtendedReadyForFile((prev) => (prev === file.id ? prev : file.id));
        }
    }, [extendedFile, extendedFileError, file.id]);

    // Tracks whether playback actually started in this session. Progress is only
    // reported once the media has played, so merely opening a movie (or having
    // the startat seek fail and currentTime sit at 0) can never overwrite a
    // stored "continue watching" position with a stale 0.
    const hasPlayedRef = useRef(false);

    // True once playback has advanced past the session's resume point. It tells
    // a deliberate user seek (which may legitimately drop below the stored
    // resume point) apart from the initial startat seek or a failed restart-to-0,
    // which must never regress the saved "continue watching" position.
    const passedResumeRef = useRef(false);
    // The engine applies the resume position (startat) with an automatic seek
    // as the FIRST seeking of the session — that one is never a user action, so
    // it must not lift the regress guard. Every later seek (seekbar drag, arrow
    // keys, click-to-seek, tap-to-seek) is user-initiated and may legitimately
    // land below the resume point (e.g. rewinding to rewatch a movie while it
    // is paused), so it unlocks saving again.
    const sessionSeekCountRef = useRef(0);
    // Once the user has deliberately sought, allow saving positions below the
    // session's resume point again (e.g. scrubbing back or rewatching a movie).
    const allowRegressRef = useRef(false);

    // Error mirror kept in a ref so `saveProgress` can gate on it without the
    // `error` state in its dependency array: the player-mount effect depends on
    // saveProgress, so a changing `error` state would otherwise tear down and
    // rebuild the (already-failed) player every time an error message changed.
    const errorRef = useRef<string | null>(null);
    useEffect(() => { errorRef.current = error; }, [error]);

    // Save progress to the backend
    const saveProgress = useCallback(() => {
        const el = elRef.current;
        if (el && !errorRef.current) {
            const position = Math.floor(el.currentTime || 0);
            // Never report 0, never report a session that never started playing,
            // and never regress a stored resume point to a smaller value (e.g.
            // when the startat seek failed and playback restarted from 0) — that
            // would wipe the user's saved watch position. Once the user has
            // deliberately sought (allowRegressRef), smaller positions are valid.
            if (position <= 0 || !hasPlayedRef.current) return;
            if (resumeStartRef.current > 0 && position < resumeStartRef.current && !allowRegressRef.current) return;
            updateProgress({
                fileId: file.id,
                position,
                duration: el.duration || 0
            });
        }
    }, [file.id, updateProgress]);

    // movi-player: construct directly via `new Ctor()` and mount into a plain
    // holder div. The engine's constructor schedules a microtask that sets the
    // host `tabindex` attribute, which violates the custom element spec — so
    // `document.createElement('movi-player')` (what React uses for <MoviTag>)
    // throws "The result must not have attributes" in WebKit and returns a
    // broken element in Chromium. Direct construction bypasses that check.
    // The engine dispatches native-like events that don't bubble, so listeners
    // are wired directly here to keep progress saving + the minimized bar in
    // sync. Playback features (quality/speed/audio/subtitles/PiP/HDR/resume,
    // gestures, hotkeys) are handled by the element's own UI.
    useEffect(() => {
        if (moviStatus !== 'ready') return;
        if (isImage) return;
        // Wait for the fresh file fetch so `resumeStartRef` holds the latest
        // last_pos before the engine is constructed — otherwise the startat
        // resume position could be read as 0 (player mounts before the fetch).
        // `extendedReadyForFile` (not `extendedFile`) gates this so later
        // refetches don't recreate the player mid-playback.
        if (extendedReadyForFile !== file.id) return;
        const holder = moviMountRef.current;
        const Ctor = (window as any).customElements?.get('movi-player');
        if (!holder || !Ctor) return;
        const el = new Ctor() as any;
        el.setAttribute('src', authorizedStreamUrl);
        el.setAttribute('autoplay', '');
        el.setAttribute('controls', '');
        el.setAttribute('playsinline', '');
        el.setAttribute('theme', 'dark');
        el.setAttribute('title', file.file_name);
        el.setAttribute('fastseek', '');
        el.setAttribute('noerrorscreen', '');
        el.setAttribute('sw', 'auto');
        hasPlayedRef.current = false;
        passedResumeRef.current = false;
        sessionSeekCountRef.current = 0;
        allowRegressRef.current = false;
        if (!isVideo) el.setAttribute('audioonly', '');
        if (resumeStartRef.current > 0) el.setAttribute('startat', String(resumeStartRef.current));
        el.style.width = '100%';
        el.style.height = '100%';
        holder.replaceChildren(el);
        elRef.current = el;
        mountedFileRef.current = file.id;
        prevTokenRef.current = reactiveToken;
        // The engine's constructor sets the host tabindex on a microtask, so
        // focus is deferred a tick. Without this the player never has focus on
        // open and its hotkeys stay dead until the user clicks the video.
        setTimeout(() => { try { el.focus({ preventScroll: true }); } catch { /* noop */ } }, 0);

        // The engine's hotkeys only fire when a keydown bubbles through the host
        // element, so any focus drift (e.g. focus lingering on the shadow-DOM
        // fullscreen button after clicking it, or on an overlay button) silently
        // kills them. On fullscreen, bring focus back so keys keep working.
        const onFullscreenChange = () => {
            if (document.fullscreenElement === el) {
                setTimeout(() => { try { el.focus({ preventScroll: true }); } catch { /* noop */ } }, 0);
            }
        };
        document.addEventListener('fullscreenchange', onFullscreenChange);

        // Broader guard: if a player control key is pressed while focus is
        // outside the player (body, overlay chrome, stale focused element),
        // route it to the player instead of dropping it. Only fires when the
        // element itself is NOT on the event path, so there's no double handling.
        const isEditableTarget = (t: any) =>
            t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement ||
            t instanceof HTMLSelectElement || !!(t as HTMLElement)?.isContentEditable;
        const isInteractiveTarget = (t: any) =>
            t instanceof HTMLElement &&
            (t.tagName === 'BUTTON' || t.tagName === 'A' || t.tagName === 'INPUT' ||
             t.tagName === 'SELECT' || t.tagName === 'TEXTAREA');
        const CONTROL_KEYS = new Set([' ', 'k', 'K', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'm', 'M', 'f', 'F', 'p', 'P', 's', 'S']);
        // Guards against the forwarded synthetic keydown re-entering this same
        // window capture listener and being re-forwarded (an infinite loop if
        // focus ever fails to land on the element).
        let forwarding = false;
        const onKeyDown = (e: KeyboardEvent) => {
            if (forwarding) return;
            if (e.defaultPrevented || isMinimizedRef.current || !CONTROL_KEYS.has(e.key)) return;
            // Skip Ctrl/Cmd/Alt combos — they belong to the browser/app
            // (Ctrl+F find, Ctrl+S save, Ctrl+P print, Alt+Arrow back/forward),
            // never to the player. Plain keys only.
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            const t = e.target as any;
            if (isEditableTarget(t) || isInteractiveTarget(t)) return;
            if (document.activeElement === el ||
                el.contains(document.activeElement as Node) ||
                el.shadowRoot?.contains(document.activeElement as Node)) return;
            e.preventDefault();
            try { el.focus({ preventScroll: true }); } catch { /* noop */ }
            forwarding = true;
            try {
                el.dispatchEvent(new KeyboardEvent('keydown', {
                    key: e.key, code: e.code, bubbles: true, cancelable: true,
                    ctrlKey: e.ctrlKey, metaKey: e.metaKey, shiftKey: e.shiftKey, altKey: e.altKey,
                }));
            } finally {
                forwarding = false;
            }
        };
        window.addEventListener('keydown', onKeyDown, true);

        const syncDuration = () => {
            const d = el.duration;
            if (typeof d === 'number' && isFinite(d) && d > 0) setDuration(d);
        };
        const onTime = () => {
            const t = el.currentTime || 0;
            setCurrentTime(t);
            if (t > resumeStartRef.current + 1) passedResumeRef.current = true;
        };
        const onLoaded = () => { syncDuration(); setIsLoading(false); };
        const onPlay = () => { hasPlayedRef.current = true; setIsPlaying(true); };
        const onPause = () => setIsPlaying(false);
        const onPlaying = () => { hasPlayedRef.current = true; setIsLoading(false); };
        const onWaiting = () => setIsLoading(true);
        const onEnded = () => { setIsPlaying(false); saveProgress(); };
        const onState = (e: any) => {
            const s = e.detail;
            // A seek that happens after playback has advanced past the resume
            // point, or after the engine's own initial startat seek (the first
            // seeking of the session), is deliberate — so allow saving below
            // the resume point from here on. The startat seek itself and any
            // failed restart-to-0 occur before that, and must never wipe the
            // saved "continue watching" position.
            if (s === 'seeking') {
                sessionSeekCountRef.current++;
                if (passedResumeRef.current || sessionSeekCountRef.current > 1) allowRegressRef.current = true;
            }
            if (s === 'buffering' || s === 'loading' || s === 'seeking') setIsLoading(true);
            else if (s === 'playing' || s === 'ready' || s === 'paused' || s === 'ended') setIsLoading(false);
            if (s === 'error') setError('Unable to play this media.');
            syncDuration();
        };
        const onError = (e?: any) => {
            setIsLoading(false);
            const msg = (e as any)?.detail?.message || 'Unable to play this media.';
            setError(msg);
        };

        el.addEventListener('timeupdate', onTime);
        el.addEventListener('durationchange', onLoaded);
        el.addEventListener('loadeddata', onLoaded);
        el.addEventListener('play', onPlay);
        el.addEventListener('pause', onPause);
        el.addEventListener('playing', onPlaying);
        el.addEventListener('waiting', onWaiting);
        el.addEventListener('ended', onEnded);
        el.addEventListener('statechange', onState);
        el.addEventListener('error', onError);

        return () => {
            saveProgress();
            document.removeEventListener('fullscreenchange', onFullscreenChange);
            window.removeEventListener('keydown', onKeyDown, true);
            el.removeEventListener('timeupdate', onTime);
            el.removeEventListener('durationchange', onLoaded);
            el.removeEventListener('loadeddata', onLoaded);
            el.removeEventListener('play', onPlay);
            el.removeEventListener('pause', onPause);
            el.removeEventListener('playing', onPlaying);
            el.removeEventListener('waiting', onWaiting);
            el.removeEventListener('ended', onEnded);
            el.removeEventListener('statechange', onState);
            el.removeEventListener('error', onError);
            if (elRef.current === el) elRef.current = null;
            try { el.dispose?.(); } catch { /* noop */ }
            holder.replaceChildren();
        };
    }, [moviStatus, file.id, authorizedStreamUrl, file.file_name, isVideo, isImage, saveProgress, extendedReadyForFile]);

    // Save progress periodically
    useEffect(() => {
        const interval = setInterval(() => {
            if (isPlaying && elRef.current && !error) saveProgress();
        }, 10000);

        return () => clearInterval(interval);
    }, [isPlaying, file.id, error, saveProgress]);

    const togglePlay = useCallback((e?: any) => {
        e?.stopPropagation();
        const el = elRef.current;
        if (!el) return;
        if (!el.paused) {
            el.pause();
            saveProgress();
        } else {
            el.play().catch(() => { /* noop */ });
        }
    }, [saveProgress]);

    const handleSkip = useCallback((seconds: number) => {
        const el = elRef.current;
        if (!el) return;
        el.currentTime = (el.currentTime || 0) + seconds;
    }, []);

    // Declare the attached external subtitle tracks on the element. This reloads
    // the source (movi-player's documented way to attach external subs); the
    // previous playhead position is restored once the media is loaded again.
    // Every track in `subtitleTracks` becomes a switchable VTT track — the
    // player's own subtitle menu then lists them alongside the native embedded
    // tracks. Re-sourcing is skipped when there are no tracks to keep a first
    // mount (empty subtitleTracks) from needlessly reloading the video.
    useEffect(() => {
        const el = elRef.current;
        if (!el || subtitleTracks.length === 0) return;
        const prevTime = el.currentTime || 0;
        const activeIdxRef = activeSubKeyRef.current === null ? -1 : subtitleTracks.findIndex((t) => t.key === activeSubKeyRef.current);
        el.source({
            video: { src: authorizedStreamUrl, type: 'video/mp4' },
            subtitles: subtitleTracks.map((t, i) => ({
                src: t.url,
                lang: `s${i}`,
                label: t.label || 'Subtitles',
                format: 'vtt',
            })),
        });
        const restore = () => {
            try {
                if (prevTime > 0) el.currentTime = prevTime;
            } catch { /* noop */ }
            // Re-apply the active track after the reloaded source registers it
            // (selecting too early, before the subtitles array is parsed, is a no-op).
            if (activeIdxRef >= 0) {
                try { el.selectSubtitleLang(`s${activeIdxRef}`); } catch { /* noop */ }
            }
            el.removeEventListener('loadeddata', restore);
        };
        el.addEventListener('loadeddata', restore);
    }, [subtitleTracks, authorizedStreamUrl]);

    // Switch the active subtitle track (null = off). The track list snapshot
    // is captured upfront so changing `subtitleTracks` after a selection does
    // not re-source the player just to keep a lang in sync.
    useEffect(() => {
        const el = elRef.current;
        if (!el) return;
        if (activeSubKey === null) {
            try { el.selectSubtitleLang(null); } catch { /* noop */ }
            return;
        }
        const idx = subtitleTracks.findIndex((t) => t.key === activeSubKey);
        if (idx === -1) return;
        try { el.selectSubtitleLang(`s${idx}`); } catch { /* noop */ }
    }, [activeSubKey]);

    const handleMouseMove = () => {
        setShowControls(true);
        if (hideControlsTimeout.current) {
            clearTimeout(hideControlsTimeout.current);
        }
        hideControlsTimeout.current = setTimeout(() => {
            if (isPlaying && !isMinimized) setShowControls(false);
        }, 3000);
    };

    useEffect(() => {
        return () => {
            if (hideControlsTimeout.current) {
                clearTimeout(hideControlsTimeout.current);
            }
        };
    }, []);

    const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

    return (
        <div
            className={`fixed transition-all duration-300 ease-in-out z-[100] ${
                isMinimized
                    ? 'bottom-0 left-0 right-0 h-20 bg-dark-900 border-t border-white/10 shadow-2xl'
                    : 'inset-0 bg-black flex items-center justify-center font-sans'
            }`}
            onMouseMove={!isMinimized ? handleMouseMove : undefined}
        >
            {/* Media Element */}
            <div className={`w-full h-full ${isMinimized ? 'hidden' : 'flex items-center justify-center'}`}>
                {isImage ? (
                    <img
                        src={imageUrl}
                        alt={file.file_name}
                        className="max-h-full max-w-full object-contain"
                        referrerPolicy="no-referrer"
                        onError={() => setError('Failed to load this image. The link may have expired — try reopening it.')}
                    />
                ) : error ? (
                    // Solid panel (no backdrop-blur, no scale animation): on
                    // Chromium a backdrop-filter element that also runs a
                    // scale transform composites the blurred backdrop on a
                    // separate layer, which can render offset from the content
                    // and look like the icon and the background are apart.
                    <div className="text-center p-8 max-w-md bg-dark-900/95 border border-white/[0.05] rounded-2xl shadow-2xl z-10 animate-fade-in">
                        <div className="w-16 h-16 rounded-2xl bg-yellow-500/20 flex items-center justify-center mx-auto mb-5 border border-yellow-500/30">
                            <AlertTriangle className="w-8 h-8 text-yellow-400" />
                        </div>
                        <h3 className="text-xl font-bold text-white mb-2">Playback Not Supported</h3>
                        <p className="text-dark-300 mb-6">{error}</p>

                        <div className="flex flex-col gap-3">
                            <a
                                href={vlcUrl}
                                className="btn-primary flex items-center justify-center gap-2"
                            >
                                <ExternalLink className="w-4 h-4" />
                                Open in VLC
                            </a>
                            <div className="flex gap-3">
                                <Button
                                    onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(externalUrl); }}
                                    className="flex-1 btn-secondary flex items-center justify-center gap-2"
                                >
                                    <Copy className="w-4 h-4" />
                                    Copy URL
                                </Button>
                                <Button
                                    onClick={(e) => { e.stopPropagation(); handleDownload(); }}
                                    className="flex-1 btn-secondary flex items-center justify-center gap-2"
                                >
                                    <Download className="w-4 h-4" />
                                    Download
                                </Button>
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="mt-6 text-dark-400 hover:text-white text-sm transition-colors"
                        >
                            Close
                        </button>
                    </div>
                ) : (
                    <>
                        {moviStatus === 'ready' && (
                            <div className="w-full h-full">
                                <div ref={moviMountRef} className="w-full h-full" />
                            </div>
                        )}

                        {/* Loading Spinner: only before the engine mounts — after
                            'ready' the engine shows its own loader in shadow DOM,
                            so showing ours too stacks two spinners on top of each
                            other (purple over the engine's white one). */}
                        {isLoading && moviStatus !== 'ready' && !isMinimized && (
                            <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-20">
                                <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-primary-500"></div>
                            </div>
                        )}
                    </>
                )}
            </div>

            {/* Slim top bar for the movi-player engine (it has its own bottom controls) */}
            {(isImage || moviStatus === 'ready') && !error && !isMinimized && (
                <div
                    className={`absolute top-0 left-0 right-0 p-4 bg-gradient-to-b from-black/80 to-transparent flex items-start justify-between z-40 transition-opacity duration-300 pointer-events-none ${
                        showControls ? 'opacity-100' : 'opacity-0'
                    }`}
                >
                    <div>
                        <h3 className="text-lg font-medium truncate max-w-lg text-white">{file.file_name}</h3>
                        {((extendedFile?.last_pos || 0) > 0) && currentTime < 5 && (
                            <p className="text-xs text-primary-400">Resumed from {formatDuration(extendedFile?.last_pos || 0)}</p>
                        )}
                    </div>
                    <div className="flex items-center gap-2 pointer-events-auto">
                        <button
                            onClick={() => setShowSubPicker(true)}
                            className={`p-2 text-white hover:bg-white/20 rounded-full transition-colors ${subtitleTracks.length > 0 ? 'text-primary-400' : ''}`}
                            title="Load Subtitles"
                        >
                            <Subtitles className="w-6 h-6" />
                        </button>
                        <button
                            onClick={() => setMinimized(true)}
                            className="p-2 text-white hover:bg-white/20 rounded-full transition-colors"
                            title="Minimize"
                        >
                            <ChevronDown className="w-6 h-6" />
                        </button>
                        <button
                            onClick={onClose}
                            className="p-2 text-white hover:bg-white/20 rounded-full transition-colors"
                        >
                            <X className="w-6 h-6" />
                        </button>
                    </div>
                </div>
            )}

            {/* Minimized Controls */}
            {isMinimized && (
                <div className="max-w-7xl mx-auto flex items-center justify-between gap-4 p-3 h-full">
                    <div className="flex items-center gap-3 overflow-hidden flex-1 cursor-pointer" onClick={() => setMinimized(false)}>
                        <div className="w-12 h-12 rounded-lg bg-dark-800 flex items-center justify-center flex-shrink-0 overflow-hidden border border-white/5 relative">
                            {file.thumbnail_url ? (
                                <AuthImage src={file.thumbnail_url} alt={file.file_name} className="w-full h-full object-cover" />
                            ) : isImage ? (
                                <img src={imageUrl} alt={file.file_name} className="w-full h-full object-cover" referrerPolicy="no-referrer" />
                            ) : (
                                isVideo ? <Film className="w-6 h-6 text-primary-400" /> : <Music className="w-6 h-6 text-primary-400" />
                            )}
                        </div>
                        <div className="truncate flex-1 min-w-0">
                            <h4 className="text-sm font-bold text-white truncate leading-tight">{file.file_name}</h4>
                            <p className="text-xs text-dark-400 font-mono">{formatDuration(currentTime)} / {formatDuration(duration)}</p>
                        </div>
                    </div>

                    <div className="flex items-center gap-3">
                        <button onClick={(e) => { e.stopPropagation(); handleSkip(-10); }} className="p-2 text-dark-300 hover:text-white">
                            <SkipBack className="w-5 h-5" />
                        </button>
                        <button
                            onClick={(e) => { e.stopPropagation(); togglePlay(); }}
                            className="p-2 bg-primary-600 rounded-full text-white hover:bg-primary-500 shadow-lg shadow-primary-500/20"
                        >
                            {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); handleSkip(10); }} className="p-2 text-dark-300 hover:text-white">
                            <SkipForward className="w-5 h-5" />
                        </button>
                    </div>

                    <div className="flex items-center gap-2 border-l border-white/10 pl-4">
                        <button onClick={() => setMinimized(false)} className="p-2 text-dark-400 hover:text-white" title="Maximize">
                            <ChevronUp className="w-5 h-5" />
                        </button>
                        <button onClick={onClose} className="p-2 text-dark-400 hover:text-red-400" title="Close">
                            <X className="w-5 h-5" />
                        </button>
                    </div>

                    {/* Progress bar line at top */}
                    <div className="absolute top-0 left-0 right-0 h-0.5 bg-dark-800">
                        <div className="h-full bg-primary-500" style={{ width: `${progressPercent}%` }}></div>
                    </div>
                </div>
            )}

            {/* Subtitle Picker: attached tracks + local upload + internet search */}
            {showSubPicker && (
                <div className="absolute inset-0 z-50 flex items-center justify-center" onClick={() => setShowSubPicker(false)}>
                    <div className="absolute inset-0 bg-black/60" />
                    <div
                        className="relative bg-dark-900/95 backdrop-blur-xl rounded-2xl border border-white/10 p-6 animate-scale-in max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <h3 className="text-lg font-bold text-white mb-1">Subtitles</h3>
                        <p className="text-sm text-dark-300 mb-4">Load from file or search the internet</p>

                        {/* Attached tracks (uploaded + internet downloads) */}
                        {subtitleTracks.length > 0 && (
                            <div className="mb-4">
                                <p className="text-xs uppercase tracking-wider text-dark-400 font-medium mb-2">Loaded tracks</p>
                                <div className="space-y-1.5">
                                    {subtitleTracks.map((t) => (
                                        <button
                                            key={t.key}
                                            onClick={() => setActiveSubKey(activeSubKey === t.key ? null : t.key)}
                                            className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg border text-left transition-colors ${
                                                activeSubKey === t.key
                                                    ? 'border-primary-500/60 bg-primary-500/10 text-primary-300'
                                                    : 'border-white/10 bg-white/[0.03] text-dark-200 hover:bg-white/[0.06]'
                                            }`}
                                            title="Click to enable / disable"
                                        >
                                            <span className="text-sm truncate">{t.label}</span>
                                            <span className="text-xs text-primary-400 flex-shrink-0">{activeSubKey === t.key ? 'ON' : 'OFF'}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Local file upload */}
                        <button
                            onClick={() => subtitleInputRef.current?.click()}
                            className="w-full py-3 border-2 border-dashed border-white/20 rounded-xl text-white/60 hover:border-primary-500/50 hover:text-primary-400 transition-colors flex flex-col items-center gap-2 mb-4"
                        >
                            <Subtitles className="w-6 h-6" />
                            <span className="text-sm font-medium">Choose .srt or .vtt file</span>
                        </button>

                        {/* Internet search */}
                        <div className="border-t border-white/10 pt-4">
                            <div className="flex items-center justify-between mb-2">
                                <p className="text-xs uppercase tracking-wider text-dark-400 font-medium">Search internet</p>
                                <button
                                    onClick={handleInternetSearch}
                                    disabled={internetLoading}
                                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary-600 hover:bg-primary-500 text-white text-xs font-medium transition-colors disabled:opacity-50"
                                >
                                    {internetLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
                                    {internetLoading ? 'Searching…' : 'Search'}
                                </button>
                            </div>

                            {internetError && (
                                <p className="text-xs text-red-400 mb-2">{internetError}</p>
                            )}

                            {internetSubs === null && !internetLoading && (
                                <p className="text-xs text-dark-400">Search OpenSubtitles and other providers for this movie / episode.</p>
                            )}

                            {internetSubs && internetSubs.length === 0 && (
                                <p className="text-xs text-dark-400">No internet subtitles found for this title.</p>
                            )}

                            {internetSubs && internetSubs.length > 0 && (
                                <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
                                    {internetSubs.map((s) => {
                                        const key = `${s.provider}:${s.id}`;
                                        const selected = selectedInternet.has(key);
                                        const alreadyLoaded = subtitleTracks.some((t) => t.key === key);
                                        return (
                                            <div
                                                key={key}
                                                onClick={() => !alreadyLoaded && toggleInternetSelect(key)}
                                                className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-left cursor-pointer transition-colors ${
                                                    alreadyLoaded
                                                        ? 'border-white/5 bg-white/[0.02] opacity-50'
                                                        : selected
                                                            ? 'border-primary-500/60 bg-primary-500/10'
                                                            : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.06]'
                                                }`}
                                            >
                                                <span className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 text-[10px] ${selected ? 'bg-primary-500 border-primary-500 text-white' : 'border-white/30'}`}>
                                                    {selected ? '✓' : ''}
                                                </span>
                                                <div className="min-w-0 flex-1">
                                                    <p className="text-sm text-white truncate">{s.name}</p>
                                                    <p className="text-[11px] text-dark-400">
                                                        {s.provider} · {s.language_name || s.language} · {s.score.toLocaleString()} downloads
                                                    </p>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}

                            {internetSubs && internetSubs.length > 0 && (
                                <button
                                    onClick={handleAttachInternet}
                                    disabled={attachingSubs || selectedInternet.size === 0}
                                    className="mt-3 w-full py-2 rounded-lg bg-primary-600 hover:bg-primary-500 text-white text-sm font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                                >
                                    {attachingSubs && <Loader2 className="w-4 h-4 animate-spin" />}
                                    {attachingSubs ? 'Attaching…' : `Add selected (${selectedInternet.size})`}
                                </button>
                            )}
                        </div>

                        <button
                            onClick={() => setShowSubPicker(false)}
                            className="mt-4 w-full py-2 text-dark-400 hover:text-white text-sm transition-colors"
                        >
                            Close
                        </button>
                    </div>
                </div>
            )}
            <input
                ref={subtitleInputRef}
                type="file"
                accept=".srt,.vtt"
                onChange={handleSubtitleFile}
                className="hidden"
            />
        </div>
    );
}

// Helper button component for cleaner code
function Button({ onClick, className, children }: { onClick?: (e: any) => void, className?: string, children: React.ReactNode }) {
    return (
        <button onClick={onClick} className={className}>
            {children}
        </button>
    );
}
