/**
 * MoveFileModal - modal for selecting a destination folder
 */
import { useState } from 'react';
import { X, Folder as FolderIcon, ChevronRight, Home } from 'lucide-react';
import { useFolderTree, TelegramFile, Folder, useMoveFiles, useMoveFolders } from '../lib/api';
import { useAppStore } from '../lib/store';

interface MoveFileModalProps {
    items: { files: TelegramFile[]; folders: Folder[] };
    onClose: () => void;
}

export default function MoveFileModal({ items, onClose }: MoveFileModalProps) {
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const { data: folderTree, isLoading } = useFolderTree();
    const { mutateAsync: moveFiles, isPending: isFilesPending } = useMoveFiles();
    const { mutateAsync: moveFolders, isPending: isFoldersPending } = useMoveFolders();
    const { addToast, clearSelection } = useAppStore();

    const isPending = isFilesPending || isFoldersPending;
    const totalItems = items.files.length + items.folders.length;

    const handleMove = async () => {
        try {
            if (items.folders.length > 0) {
                // Prevent moving a folder into itself or any of its descendants.
                // Validate before any mutation is dispatched.
                const folderIds = new Set(items.folders.map(f => f.id));
                const descendants = new Set<number>();
                const collectSubtree = (nodes: Folder[] | undefined) => {
                    nodes?.forEach(n => {
                        descendants.add(n.id);
                        collectSubtree(n.children);
                    });
                };
                // Descend the tree; anything under a moved folder (not itself
                // another moved folder) is an invalid destination.
                const findMoved = (nodes: Folder[] | undefined) => {
                    nodes?.forEach(n => {
                        if (folderIds.has(n.id)) {
                            collectSubtree(n.children);
                        } else {
                            findMoved(n.children);
                        }
                    });
                };
                findMoved(folderTree);
                if (selectedId != null && (folderIds.has(selectedId) || descendants.has(selectedId))) {
                    addToast('Cannot move a folder into itself or its subfolder', 'error');
                    return;
                }
            }

            const promises = [];
            if (items.files.length > 0) {
                promises.push(moveFiles({ ids: items.files.map(f => f.id), folderId: selectedId }));
            }
            if (items.folders.length > 0) {
                promises.push(moveFolders({ ids: items.folders.map(f => f.id), folderId: selectedId }));
            }

            await Promise.all(promises);
            addToast(`Moved ${totalItems} item(s) successfully`);
            clearSelection();
            onClose();
        } catch (error) {
            addToast('Failed to move items', 'error');
        }
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-fade-in">
            <div className="glass-card w-full max-w-md p-6 animate-scale-in">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold">Move {totalItems} Item{totalItems !== 1 ? 's' : ''}</h2>
                    <button onClick={onClose} className="p-1 hover:bg-dark-700 rounded">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <p className="text-sm text-dark-400 mb-4 truncate">
                    Select destination folder
                </p>

                <div className="bg-dark-800 rounded-lg max-h-64 overflow-y-auto mb-4">
                    {/* Root option */}
                    <button
                        onClick={() => setSelectedId(null)}
                        className={`w-full flex items-center gap-2 px-4 py-3 hover:bg-dark-700 transition-colors ${selectedId === null ? 'bg-primary-600/20 text-primary-400' : ''
                            }`}
                    >
                        <Home className="w-4 h-4" />
                        <span>Root (No folder)</span>
                    </button>

                    {isLoading ? (
                        <div className="p-4 text-center text-dark-400">Loading...</div>
                    ) : (
                        folderTree?.map((folder) => (
                            <FolderTreeItem
                                key={folder.id}
                                folder={folder}
                                selectedId={selectedId}
                                onSelect={setSelectedId}
                                depth={0}
                            />
                        ))
                    )}
                </div>

                <div className="flex justify-end gap-3">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-dark-400 hover:text-white transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleMove}
                        disabled={isPending}
                        className="px-4 py-2 bg-primary-600 hover:bg-primary-700 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        {isPending ? (
                            <>
                                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                Moving...
                            </>
                        ) : (
                            'Move Here'
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
}

function FolderTreeItem({ folder, selectedId, onSelect, depth }: {
    folder: Folder;
    selectedId: number | null;
    onSelect: (id: number) => void;
    depth: number;
}) {
    const [expanded, setExpanded] = useState(true);
    const hasChildren = folder.children && folder.children.length > 0;

    return (
        <div>
            <button
                onClick={() => onSelect(folder.id)}
                className={`w-full flex items-center gap-2 px-4 py-2 hover:bg-dark-700 transition-colors ${selectedId === folder.id ? 'bg-primary-600/20 text-primary-400' : ''
                    }`}
                style={{ paddingLeft: `${16 + depth * 16}px` }}
            >
                {hasChildren && (
                    <div
                        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
                        className="p-0.5"
                    >
                        <ChevronRight className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`} />
                    </div>
                )}
                {!hasChildren && <div className="w-4" />}
                <FolderIcon className="w-4 h-4 text-primary-400" />
                <span className="truncate">{folder.name}</span>
                <span className="text-xs text-dark-500 ml-auto">{folder.file_count}</span>
            </button>

            {expanded && hasChildren && folder.children?.map((child) => (
                <FolderTreeItem
                    key={child.id}
                    folder={child}
                    selectedId={selectedId}
                    onSelect={onSelect}
                    depth={depth + 1}
                />
            ))}
        </div>
    );
}
