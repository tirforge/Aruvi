import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '../lib/store';
import { TelegramFile, Folder, api, useFolders, getFileDownloadToken, useAccessToken, backendUrl, isTrustedBackendUrl } from '../lib/api';
import { Play, Download, Link, Edit, FolderInput, Trash2, Globe, ShieldOff, HardDriveDownload, ExternalLink } from 'lucide-react';

export default function GlobalContextMenu() {
    // Narrow selectors: this component mounts permanently at the app root —
    // a whole-store subscription re-rendered it on every drag/toast/selection.
    const activeContextMenu = useAppStore((s) => s.activeContextMenu);
    const setActiveContextMenu = useAppStore((s) => s.setActiveContextMenu);
    const setPreviewFile = useAppStore((s) => s.setPreviewFile);
    const setMoveItems = useAppStore((s) => s.setMoveItems);
    const setDeleteConfirm = useAppStore((s) => s.setDeleteConfirm);
    const setRenameFile = useAppStore((s) => s.setRenameFile);
    const setRenameFolder = useAppStore((s) => s.setRenameFolder);
    const addToast = useAppStore((s) => s.addToast);
    const selectedFileIds = useAppStore((s) => s.selectedFileIds);
    const selectedFolderIds = useAppStore((s) => s.selectedFolderIds);
    const selectedFiles = useAppStore((s) => s.selectedFiles);
    const currentFolderId = useAppStore((s) => s.currentFolderId);
    // Reactive: the token may be written after this menu mounts (e.g. the
    // /auth callback logs in without a page reload), so `hasToken` must re-
    // evaluate instead of being captured once at mount — otherwise the folder
    // list for multi-select menus stays disabled for the whole session.
    const hasToken = !!useAccessToken();
    const { data: folders } = useFolders(currentFolderId, hasToken);
    const selectedFolders = folders?.filter(f => selectedFolderIds.has(f.id)) || [];
    const menuRef = useRef<HTMLDivElement>(null);
    const [copiedId, setCopiedId] = useState<string | null>(null);
    // One timer drives the "✓ Copied!" reset: without the ref, rapid copies
    // stacked timers and an early one cleared a newer confirmation; without
    // the unmount cleanup the timer could setState on an unmounted menu.
    const copyTimerRef = useRef<number | null>(null);
    useEffect(() => {
        return () => {
            if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
        };
    }, []);
    // Reset the "✓ Copied!" confirmation when the menu (re)opens: without
    // this a reopen within the 2s timer window shows a stale confirmation
    // for an action the user hasn't taken in this menu.
    useEffect(() => {
        if (activeContextMenu) setCopiedId(null);
    }, [activeContextMenu]);
    // In-flight guard for the async share/link actions. Without it the menu
    // stays open during the POST and rapid clicks mint duplicate share links
    // (or duplicate revokes). The menu intentionally stays open for the
    // "✓ Copied!" feedback — so the buttons disable instead of closing.
    const [busyId, setBusyId] = useState<string | null>(null);
    // Sync guard alongside the state above: state updates lag a render, so a
    // fast double-click could pass the `busyId` check twice and mint
    // duplicate links. The ref is checked synchronously (same fix class as
    // GrabSearch's grabbingRef); the state still drives button disabling.
    const busyRef = useRef(false);
    const runBusy = async (id: string, fn: () => Promise<void>) => {
        if (busyRef.current) return;
        busyRef.current = true;
        setBusyId(id);
        try { await fn(); } finally { busyRef.current = false; setBusyId(null); }
    };

    // Close menu on escape; restore focus to the opener (card button) so
    // keyboard users don't drop to <body> after every menu action. The menu
    // is permanently mounted, so capture on open, restore on close-cleanup.
    const menuOpenerRef = useRef<HTMLElement | null>(null);
    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                setActiveContextMenu(null);
            }
        };
        if (activeContextMenu) {
            menuOpenerRef.current = document.activeElement as HTMLElement | null;
            document.addEventListener('keydown', handleEscape);
        }
        return () => {
            document.removeEventListener('keydown', handleEscape);
            if (menuOpenerRef.current) {
                try { menuOpenerRef.current.focus?.({ preventScroll: true }); } catch { /* noop */ }
                menuOpenerRef.current = null;
            }
        };
    }, [activeContextMenu, setActiveContextMenu]);

    if (!activeContextMenu) return null;

    const { x, y } = activeContextMenu;
    const isMultiSelect = selectedFileIds.size > 1 && activeContextMenu.type === 'file' && selectedFileIds.has(activeContextMenu.item.id);

    // Adjust position to keep within viewport
    const getMenuPosition = () => {
        const menuWidth = 220;
        const padding = 10;

        let posX = x;
        let posY = y;

        if (posX + menuWidth > window.innerWidth - padding) {
            posX = window.innerWidth - menuWidth - padding;
        }
        if (posY > window.innerHeight - 300) {
            posY = Math.max(padding, window.innerHeight - 300);
        }

        return { left: posX, top: posY };
    };

    const position = getMenuPosition();

    const handleAction = (action: () => void) => {
        action();
        setActiveContextMenu(null);
    };

    const handleCopy = async (text: string, id: string) => {
        try {
            await navigator.clipboard.writeText(text);
            setCopiedId(id);
            if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
            copyTimerRef.current = window.setTimeout(() => {
                setCopiedId(null);
                copyTimerRef.current = null;
            }, 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
            addToast('Copy failed (browser blocked clipboard)', 'error');
        }
    };

    // --- File Actions ---
    const handlePlay = (file: TelegramFile) => {
        setPreviewFile(file);
    };


    const handleRevokeShare = async (file: TelegramFile) => {
        try {
            const { data } = await api.delete<{ public_stream_url?: string }>(`/files/${file.id}/share`);
            if (activeContextMenu && activeContextMenu.type === 'file') {
                setActiveContextMenu({ ...activeContextMenu, item: { ...file, ...data } });
            }
        } catch (error) {
            console.error('Failed to revoke share:', error);
        }
    };

    const ensurePublicLink = async (file: TelegramFile): Promise<string | null> => {
        // backendUrl resolves against API_BASE: the frontend origin is wrong
        // on split deploys, and public_stream_url is a backend-relative path.
        if (file.public_stream_url) {
            return backendUrl(file.public_stream_url);
        }
        try {
            const { data } = await api.post(`/files/${file.id}/share`);
            if (data.public_stream_url) {
                if (activeContextMenu && activeContextMenu.type === 'file') {
                    setActiveContextMenu({ ...activeContextMenu, item: data });
                }
                return backendUrl(data.public_stream_url);
            }
        } catch (err) {
            console.error('Failed to create public link:', err);
            addToast('Could not create share link', 'error');
        }
        return null;
    };

    const handleDownload = async (file: TelegramFile) => {
        try {
            let token = localStorage.getItem('access_token') || '';
            try {
                token = await getFileDownloadToken(file.id);
            } catch (err) {
                console.warn('Failed to get download token, falling back to session token:', err);
            }
            // backendUrl resolves against API_BASE: naive baseURL string
            // concat double-slashed (and 404d) when the backend base carries
            // a trailing slash.
            const url = backendUrl(`/stream/dl?id=${file.id}&token=${encodeURIComponent(token)}`);
            if (!url) throw new Error('bad download url');
            window.open(url, '_blank', 'noopener,noreferrer');
        } catch (err) {
            console.error('Failed to download:', err);
        }
    };

    // --- Render ---

    return (
        <>
            {/* Overlay to catch clicks outside */}
            <div
                className="fixed inset-0 z-[99998]"
                onClick={(e) => {
                    e.stopPropagation();
                    setActiveContextMenu(null);
                }}
            />

            {/* Context Menu */}
            <div
                ref={menuRef}
                className="fixed bg-dark-800/95 backdrop-blur-xl border border-white/[0.08] rounded-xl shadow-2xl py-1.5 min-w-[220px] z-[99999] animate-scale-in"
                style={{
                    left: position.left,
                    top: position.top,
                    transformOrigin: 'top left'
                }}
                onClick={(e) => e.stopPropagation()}
                onContextMenu={(e) => e.preventDefault()}
            >
                {activeContextMenu.type === 'file' ? (
                    // File Context Menu
                    <>
                        {isMultiSelect ? (
                            <>
                                <div className="px-3 py-2 text-xs font-medium text-dark-400 uppercase tracking-wider">
                                    {selectedFileIds.size + selectedFolderIds.size} Selected
                                </div>
                                <button className="context-menu-item w-full text-left" onClick={() => handleAction(() => setMoveItems({ files: selectedFiles, folders: selectedFolders }))}>
                                    <FolderInput className="w-4 h-4" />
                                    Move ({selectedFileIds.size + selectedFolderIds.size}) Items
                                </button>
                                <button className="context-menu-item w-full text-left text-red-400 hover:bg-red-500/10" onClick={() => handleAction(() => setDeleteConfirm({ type: 'multiple', items: [...selectedFiles, ...selectedFolders] }))}>
                                    <Trash2 className="w-4 h-4" />
                                    Delete ({selectedFileIds.size + selectedFolderIds.size}) Items
                                </button>
                            </>
                        ) : (
                            <>
                                {(() => {
                                    const f = activeContextMenu.item as TelegramFile;
                                    const isPlayable = f.file_type === 'video' || f.file_type === 'audio' || f.file_type === 'image'
                                        || f.mime_type?.startsWith('video/') || f.mime_type?.startsWith('audio/') || f.mime_type?.startsWith('image/');
                                    return isPlayable && (<>
                                        <button className="context-menu-item w-full text-left" onClick={() => handleAction(() => handlePlay(f))}>
                                            <Play className="w-4 h-4" />
                                            Play
                                        </button>
                                        <button className="context-menu-item w-full text-left" onClick={() => {
                                            handleAction(() => {});
                                            // Short-lived file-bound token: the URL is handed to an
                                            // external app — never embed the account-wide JWT.
                                            void (async () => {
                                                try {
                                                    // backendUrl (API_BASE-aware): the frontend origin is
                                                    // wrong on split deploys, and prepending any origin
                                                    // to an absolute stream_url corrupts it. The minted
                                                    // token is encoded (a future alphabet change must not
                                                    // break the query string), and the resolved origin is
                                                    // gated — this URL is handed to an external app, so a
                                                    // foreign stream_url must never receive our token.
                                                    const minted = await getFileDownloadToken(f.id);
                                                    const base = backendUrl(f.stream_url);
                                                    if (!isTrustedBackendUrl(base)) throw new Error('Untrusted stream origin');
                                                    const sep = base.includes('?') ? '&' : '?';
                                                    const url = f.public_stream_url
                                                        ? backendUrl(f.public_stream_url)
                                                        : `${base}${sep}token=${encodeURIComponent(minted)}`;
                                                    if (!isTrustedBackendUrl(url)) throw new Error('Untrusted stream origin');
                                                    // Sink-side scheme gate (tssecurity:S6105): the
                                                    // open-redirect sink must visibly refuse
                                                    // non-http(s) URLs instead of relying only on
                                                    // the origin helper above.
                                                    {
                                                        const protocol = new URL(url).protocol;
                                                        if (protocol !== 'http:' && protocol !== 'https:') throw new Error('Untrusted stream origin');
                                                    }
                                                    window.open(`vlc://${url}`, '_blank', 'noopener,noreferrer');
                                                } catch (err) {
                                                    console.error('Failed to mint stream token:', err);
                                                    addToast('Could not open in VLC', 'error');
                                                }
                                            })();
                                        }}>
                                            <ExternalLink className="w-4 h-4" />
                                            Play in VLC
                                        </button>
                                        <button className="context-menu-item w-full text-left" onClick={() => {
                                            handleAction(() => {});
                                            // Clipboard URLs end up in logs/chat history — mint a
                                            // short-lived file-bound token, not the account JWT.
                                            void (async () => {
                                                try {
                                                    // backendUrl (API_BASE-aware) — see Play in VLC above.
                                                    // Same encoding + origin gate: clipboard URLs end up
                                                    // in logs/chat history, never leak a token outward.
                                                    const mintedCopy = await getFileDownloadToken(f.id);
                                                    const baseCopy = backendUrl(f.stream_url);
                                                    if (!isTrustedBackendUrl(baseCopy)) throw new Error('Untrusted stream origin');
                                                    const sepCopy = baseCopy.includes('?') ? '&' : '?';
                                                    const url = f.public_stream_url
                                                        ? backendUrl(f.public_stream_url)
                                                        : `${baseCopy}${sepCopy}token=${encodeURIComponent(mintedCopy)}`;
                                                    if (!isTrustedBackendUrl(url)) throw new Error('Untrusted stream origin');
                                                    await navigator.clipboard.writeText(url);
                                                    addToast('Stream URL copied', 'success');
                                                } catch (err) {
                                                    console.error('Failed to mint stream token:', err);
                                                    addToast('Could not copy stream URL', 'error');
                                                }
                                            })();
                                        }}>
                                            <Link className="w-4 h-4" />
                                            Copy Stream URL
                                        </button>
                                    </>);
                                })()}
                                <button
                                    className="context-menu-item w-full text-left"
                                    onClick={() => handleAction(() => handleDownload(activeContextMenu.item as TelegramFile))}
                                >
                                    <Download className="w-4 h-4" />
                                    Download
                                </button>
                                
                                <hr className="border-white/[0.08] my-1" />

                                <button className="context-menu-item w-full text-left disabled:opacity-50" disabled={busyId !== null} onClick={() => { void runBusy('download', async () => {
                                    const url = await ensurePublicLink(activeContextMenu.item as TelegramFile);
                                    if (url) handleCopy(url + (url.includes('?') ? '&' : '?') + 'download=1', 'download');
                                });}}>
                                    <HardDriveDownload className="w-4 h-4" />
                                    {copiedId === 'download' ? '✓ Copied!' : 'Copy Download URL'}
                                </button>

                                <hr className="border-white/[0.08] my-1" />

                                {(() => {
                                    const f = activeContextMenu.item as TelegramFile;
                                    if (f.public_stream_url) {
                                        return (
                                            <>
                                                <button className="context-menu-item w-full text-left disabled:opacity-50" disabled={busyId !== null} onClick={() => { void runBusy('public', async () => {
                                                    const url = await ensurePublicLink(f);
                                                    if (url) handleCopy(url, 'public');
                                                });}}>
                                                    <Globe className="w-4 h-4 text-emerald-400" />
                                                    {copiedId === 'public' ? '✓ Copied!' : 'Copy Public Link'}
                                                </button>
                                                <button className="context-menu-item w-full text-left text-orange-400 hover:bg-orange-500/10 disabled:opacity-50" disabled={busyId !== null} onClick={() => { void runBusy('revoke', async () => handleRevokeShare(f));}}>
                                                    <ShieldOff className="w-4 h-4" />
                                                    Revoke Public Link
                                                </button>
                                            </>
                                        );
                                    }
                                    return (
                                        <button className="context-menu-item w-full text-left disabled:opacity-50" disabled={busyId !== null} onClick={() => { void runBusy('public', async () => {
                                            const url = await ensurePublicLink(f);
                                            if (url) handleCopy(url, 'public');
                                        });}}>
                                            <Globe className="w-4 h-4" />
                                            {copiedId === 'public' ? '✓ Copied!' : 'Copy Public Link'}
                                        </button>
                                    );
                                })()}

                                <hr className="border-white/[0.08] my-1" />
                                
                                <button className="context-menu-item w-full text-left" onClick={() => handleAction(() => setRenameFile(activeContextMenu.item as TelegramFile))}>
                                    <Edit className="w-4 h-4" />
                                    Rename
                                </button>
                                <button className="context-menu-item w-full text-left" onClick={() => handleAction(() => setMoveItems({ files: [activeContextMenu.item as TelegramFile], folders: [] }))}>
                                    <FolderInput className="w-4 h-4" />
                                    Move to...
                                </button>
                                
                                <hr className="border-white/[0.08] my-1" />
                                
                                <button className="context-menu-item w-full text-left text-red-400 hover:bg-red-500/10" onClick={() => handleAction(() => setDeleteConfirm({ type: 'file', items: [activeContextMenu.item] }))}>
                                    <Trash2 className="w-4 h-4" />
                                    Delete
                                </button>
                            </>
                        )}
                    </>
                ) : (
                    // Folder Context Menu
                    <>
                        <button
                            className="context-menu-item w-full text-left"
                            onClick={() => handleAction(() => setRenameFolder(activeContextMenu.item as Folder))}
                        >
                            <Edit className="w-4 h-4" />
                            Rename
                        </button>
                        <hr className="border-white/[0.08] my-1" />
                        <button
                            className="context-menu-item w-full text-left text-red-400 hover:bg-red-500/10"
                            onClick={() => handleAction(() => setDeleteConfirm({ type: 'folder', items: [activeContextMenu.item] }))}
                        >
                            <Trash2 className="w-4 h-4" />
                            Delete
                        </button>
                    </>
                )}
            </div>
        </>
    );
}
