/**
 * FileCard component - displays a single file in grid or list view
 */
import { Play, MoreVertical, Film, Music, FileText, Image } from 'lucide-react';
import { TelegramFile, formatFileSize, formatDuration, useAccessToken } from '../lib/api';
import { useAppStore } from '../lib/store';
import AuthImage from './AuthImage';

interface FileCardProps {
    file: TelegramFile;
    viewMode: 'grid' | 'list';
    selected: boolean;
    onSelect: (multi: boolean) => void;
    onPlay: () => void;
}

export default function FileCard({
    file,
    viewMode,
    selected,
    onSelect,
    onPlay
}: FileCardProps) {
    const { activeContextMenu, setActiveContextMenu } = useAppStore();

    // Reactive token (not a one-shot read): the image srcs below embed it, and
    // if it's rotated mid-session a stale capture would 401 forever. This hook
    // re-renders the card on refresh so thumbnails reload with the fresh token.
    const accessToken = useAccessToken();

    // Check if this file's context menu is active
    const showMenu = activeContextMenu?.type === 'file' && activeContextMenu?.item.id === file.id;

    const handleContextMenu = (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (!selected) {
            onSelect(false);
        }
        setActiveContextMenu({ type: 'file', item: file, x: e.clientX, y: e.clientY });
    };

    const handleClick = (e: React.MouseEvent) => {
        e.stopPropagation();
        onSelect(e.ctrlKey || e.metaKey || e.shiftKey);
    };

    const handleDoubleClick = (e: React.MouseEvent) => {
        e.stopPropagation();
        onPlay();
    };

    const getIcon = () => {
        switch (file.file_type) {
            case 'video': return <Film className="w-8 h-8 text-primary-400" />;
            case 'audio': return <Music className="w-8 h-8 text-pink-400" />;
            case 'image': return <Image className="w-8 h-8 text-emerald-400" />;
            default: return <FileText className="w-8 h-8 text-blue-400" />;
        }
    };

    const getSmallIcon = () => {
        switch (file.file_type) {
            case 'video': return <Film className="w-3 h-3 text-primary-400" />;
            case 'audio': return <Music className="w-3 h-3 text-pink-400" />;
            case 'image': return <Image className="w-3 h-3 text-emerald-400" />;
            default: return <FileText className="w-3 h-3 text-blue-400" />;
        }
    };

    if (viewMode === 'list') {
        return (
            <div
                className={`flex items-center gap-4 p-3 rounded-xl cursor-pointer transition-all duration-200 animate-slide-up active:scale-[0.99]
                    ${selected
                        ? 'bg-primary-500/10 border border-primary-500/30'
                        : 'glass-card hover:bg-white/[0.03] border-white/[0.05]'
                    }`}
                draggable
                onDragStart={(e) => {
                    e.dataTransfer.setData('text/plain', String(file.id));
                    e.dataTransfer.setData('application/json', JSON.stringify({ type: 'file', id: file.id }));
                }}
                onClick={handleClick}
                onContextMenu={handleContextMenu}
                onDoubleClick={handleDoubleClick}
                data-file-id={file.id}
            >
                <div className="w-12 h-12 rounded-lg bg-dark-800/80 flex items-center justify-center overflow-hidden shrink-0 border border-white/[0.05]">
                    {file.file_type === 'image' ? (
                        <img
                            src={`${window.location.origin}${file.stream_url}?token=${accessToken}`}
                            alt={file.file_name}
                            className="w-full h-full object-cover"
                            referrerPolicy="no-referrer"
                        />
                    ) : file.thumbnail_url ? (
                        <AuthImage src={file.thumbnail_url} alt={file.file_name} className="w-full h-full object-cover" />
                    ) : (
                        getIcon()
                    )}
                </div>

                <div className="flex-1 min-w-0">
                    <p className={`font-medium truncate text-sm ${selected ? 'text-primary-200' : 'text-white'}`}>{file.file_name}</p>
                    <div className="flex items-center gap-3 text-xs text-dark-400 mt-1">
                        <span className="flex items-center gap-1">
                            {getSmallIcon()}
                            <span className="capitalize">{file.file_type}</span>
                        </span>
                        <span className="w-1 h-1 rounded-full bg-dark-600"></span>
                        <span>{formatFileSize(file.file_size)}</span>
                        {file.duration && (
                            <>
                                <span className="w-1 h-1 rounded-full bg-dark-600"></span>
                                <span>{formatDuration(file.duration)}</span>
                            </>
                        )}
                        {file.last_pos && file.duration && (file.last_pos / file.duration > 0.05) && (
                            <>
                                <span className="w-1 h-1 rounded-full bg-dark-600"></span>
                                <span className="text-primary-400">
                                    {Math.round((file.last_pos / file.duration) * 100)}%
                                </span>
                            </>
                        )}
                    </div>
                </div>

                <div className="relative">
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            if (showMenu) {
                                setActiveContextMenu(null);
                            } else {
                                const rect = e.currentTarget.getBoundingClientRect();
                                setActiveContextMenu({ type: 'file', item: file, x: rect.right, y: rect.bottom });
                            }
                        }}
                        className={`p-2 rounded-lg transition-colors ${showMenu ? 'bg-white/10 text-white' : 'hover:bg-white/[0.08] text-dark-400'}`}
                    >
                        <MoreVertical className="w-4 h-4" />
                    </button>
                </div>
            </div>
        );
    }

    // Grid view
    return (
        <div
            className={`p-3 rounded-xl cursor-pointer transition-all duration-300 group relative animate-scale-in select-none
                ${selected
                    ? 'bg-primary-500/10 border border-primary-500/30 shadow-lg shadow-primary-500/5'
                    : 'glass-card hover:bg-dark-800/60 hover:shadow-xl hover:shadow-black/20 hover:-translate-y-1'
                }`}
            draggable
            onDragStart={(e) => {
                    e.dataTransfer.setData('text/plain', String(file.id));
                    e.dataTransfer.setData('application/json', JSON.stringify({ type: 'file', id: file.id }));
                }}
            onClick={handleClick}
            onContextMenu={handleContextMenu}
            onDoubleClick={handleDoubleClick}
            data-file-id={file.id}
        >
            <div className={`aspect-video rounded-lg mb-3 overflow-hidden relative border ${selected ? 'border-primary-500/20' : 'border-white/[0.05]'} bg-dark-900/50`}>
                {file.file_type === 'image' ? (
                    <img
                        src={`${window.location.origin}${file.stream_url}?token=${accessToken}`}
                        alt={file.file_name}
                        className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                        referrerPolicy="no-referrer"
                    />
                ) : file.thumbnail_url ? (
                    <>
                        <AuthImage src={file.thumbnail_url} alt={file.file_name} className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105" />
                        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
                    </>
                ) : (
                    <div className="w-full h-full flex items-center justify-center">
                        {getIcon()}
                    </div>
                )}

                {/* Progress Bar */}
                {file.last_pos && file.duration && (file.last_pos / file.duration > 0.05) && (
                    <div className="absolute bottom-0 left-0 right-0 h-1 bg-black/40">
                        <div 
                            className="h-full bg-primary-500" 
                            style={{ width: `${Math.min(100, (file.last_pos / file.duration) * 100)}%` }}
                        />
                    </div>
                )}

                {/* Duration badge */}
                {file.duration && (
                    <div className="absolute bottom-1.5 right-1.5 bg-black/60 backdrop-blur-md px-1.5 py-0.5 rounded text-[10px] font-medium text-white shadow-sm">
                        {formatDuration(file.duration)}
                    </div>
                )}

                {/* Play overlay for video/audio/image */}
                {(file.file_type === 'video' || file.file_type === 'audio' || file.file_type === 'image') && (
                    <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all duration-300">
                        <div className="w-10 h-10 rounded-full bg-white/10 backdrop-blur-md flex items-center justify-center shadow-lg border border-white/20 hover:scale-110 transition-transform">
                            <Play className="w-4 h-4 text-white ml-0.5" fill="currentColor" />
                        </div>
                    </div>
                )}
            </div>

            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                    <p className={`font-medium text-sm truncate transition-colors ${selected ? 'text-primary-200' : 'text-white group-hover:text-primary-300'}`} title={file.file_name}>
                        {file.file_name}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                        <span className={`flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md border ${
                            selected 
                            ? 'bg-primary-500/20 border-primary-500/20 text-primary-300' 
                            : 'bg-dark-800 border-white/[0.05] text-dark-400 group-hover:border-white/[0.1]'
                        }`}>
                            {getSmallIcon()}
                            <span className="capitalize">{file.file_type}</span>
                        </span>
                        <p className="text-[10px] text-dark-500">
                            {formatFileSize(file.file_size)}
                        </p>
                    </div>
                </div>

                <div className={`${showMenu ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} transition-opacity`}>
                   <button
                        onClick={(e) => {
                            e.stopPropagation();
                            if (showMenu) {
                                setActiveContextMenu(null);
                            } else {
                                const rect = e.currentTarget.getBoundingClientRect();
                                setActiveContextMenu({ type: 'file', item: file, x: rect.right, y: rect.bottom });
                            }
                        }}
                        className={`p-1.5 rounded-lg transition-colors ${showMenu ? 'bg-white/10 text-white' : 'hover:bg-white/[0.08] text-dark-400'}`}
                    >
                        <MoreVertical className="w-4 h-4" />
                    </button> 
                </div>
            </div>
        </div>
    );
}
