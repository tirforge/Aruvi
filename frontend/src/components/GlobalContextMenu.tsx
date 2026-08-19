import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '../lib/store';
import { TelegramFile, Folder, api, useFolders, getFileDownloadToken, useAccessToken } from '../lib/api';
import { Play, Download, Link, Edit, FolderInput, Trash2, Globe, ShieldOff, HardDriveDownload, ExternalLink } from 'lucide-react';

export default function GlobalContextMenu() {
    const { activeContextMenu, setActiveContextMenu, setPreviewFile, setMoveItems, setDeleteConfirm, setRenameFile, setRenameFolder, selectedFileIds, selectedFolderIds, selectedFiles, currentFolderId } = useAppStore();
    // Reactive: the token may be written after this menu mounts (e.g. the
    // /auth callback logs in without a page reload), so `hasToken` must re-
    // evaluate instead of being captured once at mount — otherwise the folder
    // list for multi-select menus stays disabled for the whole session.
    const hasToken = !!useAccessToken();
    const { data: folders } = useFolders(currentFolderId, hasToken);
    const selectedFolders = folders?.filter(f => selectedFolderIds.has(f.id)) || [];
    const menuRef = useRef<HTMLDivElement>(null);
    const [copiedId, setCopiedId] = useState<string | null>(null);

    // Close menu on escape
    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                setActiveContextMenu(null);
            }
        };
        if (activeContextMenu) {
            document.addEventListener('keydown', handleEscape);
        }
        return () => document.removeEventListener('keydown', handleEscape);
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
            setTimeout(() => setCopiedId(null), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
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
        if (file.public_stream_url) {
            return `${window.location.protocol}//${window.location.host}${file.public_stream_url}`;
        }
        try {
            const { data } = await api.post(`/files/${file.id}/share`);
            if (data.public_stream_url) {
                if (activeContextMenu && activeContextMenu.type === 'file') {
                    setActiveContextMenu({ ...activeContextMenu, item: data });
                }
                return `${window.location.protocol}//${window.location.host}${data.public_stream_url}`;
            }
        } catch (err) {
            console.error('Failed to create public link:', err);
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
            const dlUrl = `${api.defaults.baseURL}/stream/dl?id=${file.id}&token=${encodeURIComponent(token)}`;
            const url = dlUrl.startsWith('http')
                ? dlUrl
                : `${window.location.protocol}//${window.location.host}${dlUrl}`;
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
                                            const token = localStorage.getItem('access_token');
                                            const baseUrl = `${window.location.protocol}//${window.location.host}`;
                                            const url = f.public_stream_url
                                                ? `${baseUrl}${f.public_stream_url}`
                                                : `${baseUrl}${f.stream_url}?token=${token}`;
                                            window.open(`vlc://${url}`, '_blank');
                                            handleAction(() => {});
                                        }}>
                                            <ExternalLink className="w-4 h-4" />
                                            Play in VLC
                                        </button>
                                        <button className="context-menu-item w-full text-left" onClick={() => {
                                            const token = localStorage.getItem('access_token');
                                            const baseUrl = `${window.location.protocol}//${window.location.host}`;
                                            const url = f.public_stream_url
                                                ? `${baseUrl}${f.public_stream_url}`
                                                : `${baseUrl}${f.stream_url}?token=${token}`;
                                            navigator.clipboard.writeText(url);
                                            handleAction(() => {});
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

                                <button className="context-menu-item w-full text-left" onClick={async () => {
                                    const url = await ensurePublicLink(activeContextMenu.item as TelegramFile);
                                    if (url) handleCopy(url + (url.includes('?') ? '&' : '?') + 'download=1', 'download');
                                }}>
                                    <HardDriveDownload className="w-4 h-4" />
                                    {copiedId === 'download' ? '✓ Copied!' : 'Copy Download URL'}
                                </button>

                                <hr className="border-white/[0.08] my-1" />

                                {(() => {
                                    const f = activeContextMenu.item as TelegramFile;
                                    if (f.public_stream_url) {
                                        return (
                                            <>
                                                <button className="context-menu-item w-full text-left" onClick={async () => {
                                                    const url = await ensurePublicLink(f);
                                                    if (url) handleCopy(url, 'public');
                                                }}>
                                                    <Globe className="w-4 h-4 text-emerald-400" />
                                                    {copiedId === 'public' ? '✓ Copied!' : 'Copy Public Link'}
                                                </button>
                                                <button className="context-menu-item w-full text-left text-orange-400 hover:bg-orange-500/10" onClick={() => handleRevokeShare(f)}>
                                                    <ShieldOff className="w-4 h-4" />
                                                    Revoke Public Link
                                                </button>
                                            </>
                                        );
                                    }
                                    return (
                                        <button className="context-menu-item w-full text-left" onClick={async () => {
                                            const url = await ensurePublicLink(f);
                                            if (url) handleCopy(url, 'public');
                                        }}>
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
