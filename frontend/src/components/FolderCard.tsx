/**
 * FolderCard component - displays a folder in grid or list view with drag-drop support
 */
import React, { useState } from 'react';
import { Folder as FolderIcon, MoreVertical, ChevronRight } from 'lucide-react';
import { Folder } from '../lib/api';
import { useAppStore } from '../lib/store';

interface FolderCardProps {
    folder: Folder;
    viewMode: 'grid' | 'list';
    selected?: boolean;
    onSelect?: (multi: boolean) => void;
    onOpen: () => void;
    onFileDrop: (fileId: number, folderId: number) => void;
}

function FolderCardImpl({ folder, viewMode, selected, onSelect, onOpen, onFileDrop }: FolderCardProps) {
    const [isDragOver, setIsDragOver] = useState(false);
    const activeContextMenu = useAppStore((s) => s.activeContextMenu);
    const setActiveContextMenu = useAppStore((s) => s.setActiveContextMenu);

    // Check if this folder's context menu is active
    const showMenu = activeContextMenu?.type === 'folder' && activeContextMenu?.item.id === folder.id;

    const handleContextMenu = (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setActiveContextMenu({ type: 'folder', item: folder, x: e.clientX, y: e.clientY });
    };

    const handleClick = (e: React.MouseEvent) => {
        if (onSelect && (e.ctrlKey || e.metaKey || e.shiftKey)) {
            e.preventDefault();
            e.stopPropagation();
            onSelect(true);
        } else {
            onOpen();
        }
    };

    const handleSelectClick = (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        onSelect?.(true);
    };

    // Drop handlers
    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        setIsDragOver(true);
    };

    const handleDragLeave = () => {
        setIsDragOver(false);
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragOver(false);

        // File cards publish both `application/json` ({type:'file', id}) and a
        // `text/plain` file id; folder cards publish only `application/json`
        // ({type:'folder', id}). Accept the JSON payload first, then fall back
        // to the raw numeric file id from text/plain.
        try {
            const data = JSON.parse(e.dataTransfer.getData('application/json'));
            if ((data.type === 'file' || data.type === 'folder') && data.id && data.type === 'file') {
                onFileDrop(data.id, folder.id);
                return;
            }
        } catch (err) {
            const plain = e.dataTransfer.getData('text/plain').trim();
            if (/^\d+$/.test(plain)) {
                onFileDrop(Number(plain), folder.id);
                return;
            }
            console.error('Invalid drop data:', err);
        }
    };

    const dropStyles = isDragOver
        ? 'ring-2 ring-primary-500 bg-primary-500/20 scale-105 shadow-xl shadow-primary-500/20'
        : '';
        
    const selectedStyles = selected 
        ? 'ring-2 ring-primary-500 bg-primary-500/10' 
        : '';

    if (viewMode === 'list') {
        return (
            <div
                className={`flex items-center gap-4 p-3 rounded-xl cursor-pointer transition-all duration-200 animate-slide-up active:scale-[0.99]
                    glass-card hover:bg-white/[0.03] border-white/[0.05] group
                    ${dropStyles} ${selectedStyles}`}
                draggable
                onDragStart={(e) => e.dataTransfer.setData('application/json', JSON.stringify({ type: 'folder', id: folder.id }))}
                onClick={handleClick}
                onContextMenu={handleContextMenu}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                data-folder-id={folder.id}
            >
                <div 
                    className={`w-12 h-12 rounded-lg flex items-center justify-center shrink-0 border transition-colors relative
                        ${selected 
                            ? 'bg-primary-500/20 border-primary-500/40' 
                            : 'bg-primary-500/10 border-primary-500/20 group-hover:bg-primary-500/20'}`}
                >
                    <FolderIcon className={`w-6 h-6 transition-colors ${selected ? 'text-primary-300' : 'text-primary-400 group-hover:text-primary-300'}`} />
                    
                    {/* Selection indicator for list view */}
                    <div 
                        onClick={handleSelectClick}
                        className={`absolute -top-1 -left-1 w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all
                            ${selected 
                                ? 'bg-primary-500 border-dark-950 scale-110 shadow-lg shadow-primary-500/20' 
                                : 'bg-dark-800 border-white/10 opacity-0 group-hover:opacity-100 hover:border-primary-500/50'}`}
                    >
                        <div className={`w-1.5 h-1.5 rounded-full bg-white transition-transform ${selected ? 'scale-100' : 'scale-0'}`} />
                    </div>
                </div>

                <div className="flex-1 min-w-0">
                    <p className={`font-medium truncate text-sm transition-colors ${selected ? 'text-primary-300' : 'text-white group-hover:text-primary-300'}`}>{folder.name}</p>
                    <p className="text-xs text-dark-400 mt-0.5">
                        {folder.file_count} {folder.file_count === 1 ? 'file' : 'files'}
                    </p>
                </div>

                <div className="relative flex items-center gap-2">
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            if (showMenu) {
                                setActiveContextMenu(null);
                            } else {
                                const rect = e.currentTarget.getBoundingClientRect();
                                setActiveContextMenu({ type: 'folder', item: folder, x: rect.right, y: rect.bottom });
                            }
                        }}
                        className={`p-2 rounded-lg transition-colors ${showMenu ? 'bg-white/10 text-white' : 'hover:bg-white/[0.08] text-dark-400 opacity-0 group-hover:opacity-100'}`}
                    >
                        <MoreVertical className="w-4 h-4" />
                    </button>
                    <ChevronRight className="w-4 h-4 text-dark-600 group-hover:text-dark-400 transition-colors" />
                </div>
            </div>
        );
    }

    // Grid view
    return (
        <div
            className={`p-4 rounded-xl cursor-pointer transition-all duration-300 group relative animate-scale-in select-none
                glass-card hover:bg-dark-800/60 hover:shadow-xl hover:shadow-black/20 hover:-translate-y-1
                ${dropStyles} ${selectedStyles}`}
            draggable
            onDragStart={(e) => e.dataTransfer.setData('application/json', JSON.stringify({ type: 'folder', id: folder.id }))}
            onClick={handleClick}
            onContextMenu={handleContextMenu}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            data-folder-id={folder.id}
        >
            <div className="flex items-start justify-between mb-3">
                <div 
                    className={`w-10 h-10 rounded-lg flex items-center justify-center border group-hover:scale-110 transition-all duration-300 relative
                        ${selected 
                            ? 'bg-gradient-to-br from-primary-500/20 to-primary-500/10 border-primary-500/40' 
                            : 'bg-gradient-to-br from-primary-500/10 to-primary-500/5 border-primary-500/20 group-hover:border-primary-500/30'}`}
                >
                    <FolderIcon className={`w-5 h-5 transition-colors ${selected ? 'text-primary-300' : 'text-primary-400'}`} />
                    
                    {/* Selection indicator for grid view */}
                    <div 
                        onClick={handleSelectClick}
                        className={`absolute -top-1.5 -left-1.5 w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all z-10
                            ${selected 
                                ? 'bg-primary-500 border-dark-900 scale-110 shadow-lg shadow-primary-500/20' 
                                : 'bg-dark-800 border-white/10 opacity-0 group-hover:opacity-100 hover:border-primary-500/50'}`}
                    >
                         <div className={`w-1.5 h-1.5 rounded-full bg-white transition-transform ${selected ? 'scale-100' : 'scale-0'}`} />
                    </div>
                </div>
                
                <button
                    onClick={(e) => {
                        e.stopPropagation();
                        if (showMenu) {
                            setActiveContextMenu(null);
                        } else {
                            const rect = e.currentTarget.getBoundingClientRect();
                            setActiveContextMenu({ type: 'folder', item: folder, x: rect.right, y: rect.bottom });
                        }
                    }}
                    className={`p-1.5 rounded-lg transition-colors ${showMenu ? 'bg-white/10 text-white' : 'hover:bg-white/[0.08] text-dark-400 opacity-0 group-hover:opacity-100'}`}
                >
                    <MoreVertical className="w-4 h-4" />
                </button>
            </div>

            <p className={`font-medium text-sm truncate transition-colors ${selected ? 'text-primary-300' : 'text-white group-hover:text-primary-300'}`} title={folder.name}>
                {folder.name}
            </p>
            <p className="text-xs text-dark-500 mt-1">
                {folder.file_count} {folder.file_count === 1 ? 'file' : 'files'}
            </p>
        </div>
    );
}

// Value-props comparison only (see FileCard): the callback props capture the
// same stable store actions on every parent render.
export default React.memo(
    FolderCardImpl,
    (prev, next) => prev.folder === next.folder && prev.viewMode === next.viewMode && prev.selected === next.selected
);
