/**
 * Main FileBrowser component - the core of the web interface
 */
import { useEffect, useCallback, useRef, useState } from 'react';
import { FolderPlus, Grid, List, Search, ChevronRight, Home, RefreshCw, Clipboard, ArrowUp, Film, Music, Image as ImageIcon, FileText, Menu } from 'lucide-react';
import { useFiles, useFolders, useUpdateFile, useUpdateFolder, useDeleteFolder, useDeleteFiles, useMoveFiles, TelegramFile, Folder, useRecentFiles, useContinueWatching, useDeleteFolders, useMoveFolders } from '../lib/api';
import { useAppStore } from '../lib/store';
import FileCard from './FileCard';
import FolderCard from './FolderCard';
import NewFolderModal from './NewFolderModal';
import MoveFileModal from './MoveFileModal';
import DeleteConfirmModal from './DeleteConfirmModal';
import RenameModal from './RenameModal';
import Sidebar from './Sidebar';
import Toasts from './Toasts';
import AdminPanel from './AdminPanel';
import GrabSearch from './GrabSearch';

export default function FileBrowser() {
    const { showAdminPanel, setShowAdminPanel } = useAppStore();
    const {
        currentFolderId,
        setCurrentFolderId,
        breadcrumbs,
        setBreadcrumbs,
        selectedFileIds,
        selectFile,
        selectedFolderIds,
        selectFolder,
        clearSelection,
        selectAll,
        viewMode,
        setViewMode,
        previewFile,
        setPreviewFile,
        showNewFolder,
        setShowNewFolder,
        moveItems,
        setMoveItems,
        deleteConfirm,
        setDeleteConfirm,
        searchQuery,
        setSearchQuery,
        fileTypeFilter,
        setFileTypeFilter,
        renameFile,
        setRenameFile,
        renameFolder,
        setRenameFolder,
        clipboard,
        setClipboard,
        selectionBox,
        setSelectionBox,
        activeSection,
        addToast,
        setSelectedFiles,
        setVisibleFiles
    } = useAppStore();

    // Pagination state
    const [page, setPage] = useState(1);
    const [hasMore, setHasMore] = useState(true);
    const [allFiles, setAllFiles] = useState<TelegramFile[]>([]);

    // Debounced file search: the input stays snappy, but the store-backed
    // searchQuery (which resets pagination and refetches) only updates after
    // the user pauses typing for 350ms, so we don't fire a request per keystroke.
    const [searchInput, setSearchInput] = useState(searchQuery);
    // Resync the local input whenever the store value changes externally (e.g.
    // a programmatic clear), and never "echo back": when the debounce commits
    // searchQuery === searchInput the value is unchanged so there's no loop.
    useEffect(() => setSearchInput(searchQuery), [searchQuery, setSearchQuery]);
    useEffect(() => {
        const t = setTimeout(() => setSearchQuery(searchInput), 350);
        return () => clearTimeout(t);
    }, [searchInput, setSearchQuery]);

    // Data Fetching
    const { data: filesList, isLoading: filesLoading, isError: filesError, refetch: refetchFiles } = useFiles(currentFolderId, fileTypeFilter || undefined, searchQuery || undefined, page);
    // Only fetch these when their section is active — otherwise every browse
    // view pays for two extra authorized requests (and refetches on focus).
    const { data: recentFiles, isLoading: recentLoading, refetch: refetchRecent } = useRecentFiles(50, activeSection === 'recent');
    const { data: cwFiles, isLoading: cwLoading, refetch: refetchCW } = useContinueWatching(50, activeSection === 'continue_watching');
    


    // Determine which files to show
    let displayFiles: TelegramFile[] | undefined;
    let isLoading = false;

    if (activeSection === 'recent') {
        displayFiles = recentFiles?.files;
        isLoading = recentLoading;
    } else if (activeSection === 'continue_watching') {
        displayFiles = cwFiles?.files;
        isLoading = cwLoading;
    } else {
        displayFiles = allFiles;
        isLoading = filesLoading;
    }

    // Folders only show in 'files' mode
    const { data: folders, isLoading: foldersLoading, refetch: refetchFolders } = useFolders(currentFolderId);
    const showFolders = activeSection === 'files' && !searchQuery && !fileTypeFilter;

    // Combined loading state
    isLoading = isLoading || (activeSection === 'files' && foldersLoading);
    
    // Mutations
    const deleteFilesMutation = useDeleteFiles();
    const deleteFolderMutation = useDeleteFolder();
    const deleteFoldersMutation = useDeleteFolders();
    const updateFileMutation = useUpdateFile();
    const moveFilesMutation = useMoveFiles();
    const moveFoldersMutation = useMoveFolders();
    const updateFolderMutation = useUpdateFolder();

    const containerRef = useRef<HTMLDivElement>(null);
    const [isSelecting, setIsSelecting] = useState(false);
    const [isSidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);
    const selectionStart = useRef({ x: 0, y: 0 });
    const pendingResetRef = useRef(false);
    const pageLoadingRef = useRef(false);

    // handle refresh
    const handleRefresh = useCallback(() => {
        if (activeSection === 'files') {
            refetchFiles();
            refetchFolders();
        } else if (activeSection === 'recent') {
            refetchRecent();
        } else if (activeSection === 'continue_watching') {
            refetchCW();
        } else if (activeSection === 'grab') {
            refetchFiles();
            refetchRecent();
        }
    }, [activeSection, refetchFiles, refetchFolders, refetchRecent, refetchCW]);

    // Handle drag-drop file to folder
    const handleFileDrop = useCallback(async (fileId: number, folderId: number) => {
        await updateFileMutation.mutateAsync({ id: fileId, folder_id: folderId });
    }, [updateFileMutation]);

    // Handle file rename
    const handleRenameFile = useCallback(async (newName: string) => {
        if (!renameFile) return;
        await updateFileMutation.mutateAsync({ id: renameFile.id, file_name: newName });
        setRenameFile(null);
    }, [renameFile, updateFileMutation, setRenameFile]);

    // Handle folder rename
    const handleRenameFolder = useCallback(async (newName: string) => {
        if (!renameFolder) return;
        await updateFolderMutation.mutateAsync({ id: renameFolder.id, name: newName });
        setRenameFolder(null);
    }, [renameFolder, updateFolderMutation, setRenameFolder]);

    // Navigate to folder
    const navigateToFolder = useCallback((folder: Folder | null) => {
        if (folder === null) {
            setCurrentFolderId(null);
            setBreadcrumbs([{ id: null, name: 'My Files' }]);
        } else {
            setCurrentFolderId(folder.id);
            setBreadcrumbs([...breadcrumbs, { id: folder.id, name: folder.name }]);
        }
        clearSelection();
    }, [breadcrumbs, clearSelection, setBreadcrumbs, setCurrentFolderId]);

    // Navigate via breadcrumbs
    const navigateToBreadcrumb = useCallback((index: number) => {
        const target = breadcrumbs[index];
        setCurrentFolderId(target.id);
        setBreadcrumbs(breadcrumbs.slice(0, index + 1));
        clearSelection();
    }, [breadcrumbs, clearSelection, setBreadcrumbs, setCurrentFolderId]);

    // Handle delete confirmation
    const handleDeleteConfirm = async () => {
        if (!deleteConfirm) return;
        const { type, items } = deleteConfirm;
        
        try {
            if (type === 'file') {
                const ids = items.map(i => i.id);
                await deleteFilesMutation.mutateAsync(ids);
            } else if (type === 'folder') {
                const ids = items.map(i => i.id);
                if (ids.length > 1) {
                    await deleteFoldersMutation.mutateAsync(ids);
                } else {
                    await deleteFolderMutation.mutateAsync({ id: ids[0] });
                }
            } else if (type === 'multiple') {
                 // Split into files and folders
                 const fileIds = items.filter(i => 'file_name' in i).map(i => i.id);
                 const folderIds = items.filter(i => 'name' in i && !('file_name' in i)).map(i => i.id);
                 
                 const promises = [];
                 if (fileIds.length > 0) promises.push(deleteFilesMutation.mutateAsync(fileIds));
                 if (folderIds.length > 0) promises.push(deleteFoldersMutation.mutateAsync(folderIds));
                 
                 await Promise.all(promises);
            }
            setDeleteConfirm(null);
            clearSelection();
            refetchFiles();
            refetchFolders();
            addToast('Items deleted successfully', 'success');
        } catch (error) {
            console.error('Delete failed:', error);
            addToast('Failed to delete items', 'error');
        }
    };



    // Handle Paste
    const handlePaste = useCallback(async () => {
        if (!clipboard) return;

        try {
            if (clipboard.mode === 'cut') {
                if (clipboard.files.length > 0) {
                    await moveFilesMutation.mutateAsync({
                        ids: clipboard.files.map(f => f.id),
                        folderId: currentFolderId
                    });
                }
                if (clipboard.folders.length > 0) {
                    await moveFoldersMutation.mutateAsync({
                        ids: clipboard.folders.map(f => f.id),
                        folderId: currentFolderId
                    });
                }
                setClipboard(null);
            } else if (clipboard.mode === 'copy') {
                alert("Copying files is not yet supported. Only Move (Cut) is supported.");
            }
        } catch (error) {
            console.error('Paste failed:', error);
        }
    }, [clipboard, currentFolderId, moveFilesMutation, moveFoldersMutation, setClipboard]);


    // Selection Box Logic
    const handleMouseDown = (e: React.MouseEvent) => {
        if (e.button !== 0) return; // Only left click
        // Rubber-band selection is for the file grid. GrabSearch renders its own
        // interactive cards inside this container, so dragging there must not
        // draw a selection rectangle over the search UI.
        if (activeSection === 'grab') return;
        // If clicking on a card or button, ignore
        if ((e.target as HTMLElement).closest('[data-file-id], [data-folder-id]') || 
            (e.target as HTMLElement).closest('button') ||
            (e.target as HTMLElement).closest('.sidebar')) return;

        setIsSelecting(true);
        // Determine relative position in the container
        const rect = containerRef.current?.getBoundingClientRect();
        if (rect) {
            const startX = e.clientX - rect.left + containerRef.current!.scrollLeft;
            const startY = e.clientY - rect.top + containerRef.current!.scrollTop;
            selectionStart.current = { x: startX, y: startY };
            setSelectionBox({ x1: startX, y1: startY, x2: startX, y2: startY, active: true });
        }
        
        if (!e.ctrlKey && !e.metaKey && !e.shiftKey) {
            clearSelection();
        }
    };

    const handleMouseMove = (e: React.MouseEvent) => {
        if (!isSelecting || !containerRef.current) return;
        
        const rect = containerRef.current.getBoundingClientRect();
        const currentX = e.clientX - rect.left + containerRef.current.scrollLeft;
        const currentY = e.clientY - rect.top + containerRef.current.scrollTop;

        setSelectionBox({
            x1: selectionStart.current.x,
            y1: selectionStart.current.y,
            x2: currentX,
            y2: currentY,
            active: true
        });

        // Calculate selection
        const box = {
            left: Math.min(selectionStart.current.x, currentX),
            top: Math.min(selectionStart.current.y, currentY),
            right: Math.max(selectionStart.current.x, currentX),
            bottom: Math.max(selectionStart.current.y, currentY),
        };

        const fileIdsToSelect: number[] = [];
        const folderIdsToSelect: number[] = [];
        
        // Check files
        const fileElements = containerRef.current.querySelectorAll('[data-file-id]');
        fileElements.forEach((el) => {
            const elRect = (el as HTMLElement).getBoundingClientRect();
            const elLeft = elRect.left - rect.left + containerRef.current!.scrollLeft;
            const elTop = elRect.top - rect.top + containerRef.current!.scrollTop;
            const elRight = elLeft + elRect.width;
            const elBottom = elTop + elRect.height;

            if (elLeft < box.right && elRight > box.left && elTop < box.bottom && elBottom > box.top) {
                fileIdsToSelect.push(Number((el as HTMLElement).dataset.fileId));
            }
        });

        // Check folders
        const folderElements = containerRef.current.querySelectorAll('[data-folder-id]');
        folderElements.forEach((el) => {
            const elRect = (el as HTMLElement).getBoundingClientRect();
            const elLeft = elRect.left - rect.left + containerRef.current!.scrollLeft;
            const elTop = elRect.top - rect.top + containerRef.current!.scrollTop;
            const elRight = elLeft + elRect.width;
            const elBottom = elTop + elRect.height;

            if (elLeft < box.right && elRight > box.left && elTop < box.bottom && elBottom > box.top) {
                folderIdsToSelect.push(Number((el as HTMLElement).dataset.folderId));
            }
        });

        if (fileIdsToSelect.length > 0 || folderIdsToSelect.length > 0) {
            selectAll(fileIdsToSelect, folderIdsToSelect);
        } else {
            clearSelection();
        }
    };

    const handleMouseUp = () => {
        if (isSelecting) {
            setIsSelecting(false);
            setSelectionBox(null);
        }
    };

    // Handle File Open / Play
    const handleFileOpen = (file: TelegramFile) => {
        const isMedia = file.file_type === 'video' || file.file_type === 'audio' || file.file_type === 'image'
            || file.mime_type?.startsWith('video/') || file.mime_type?.startsWith('audio/') || file.mime_type?.startsWith('image/');
        if (isMedia) {
            setPreviewFile(file);
        }
        // Prevent opening empty player
    };

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            // Ignore if input/textarea is focused or player is open
            if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || previewFile) return;

            // Ctrl+Shift+N - New Folder
            if (e.ctrlKey && e.shiftKey && (e.key === 'N' || e.key === 'n')) {
                e.preventDefault();
                setShowNewFolder(true);
                return;
            }

            // F5 or Ctrl+R - Refresh
            if (e.key === 'F5' || (e.ctrlKey && e.key === 'r')) {
                e.preventDefault();
                handleRefresh();
                return;
            }

            // Escape - exit fullscreen, or close modals / clear selection
            if (e.key === 'Escape') {
                if (document.fullscreenElement) document.exitFullscreen();
                else if (showNewFolder) setShowNewFolder(false);
                else if (moveItems) setMoveItems(null);
                else if (deleteConfirm) setDeleteConfirm(null);
                else clearSelection();
            }

            // Ctrl+A - select all
            if (e.ctrlKey && e.key === 'a' && displayFiles) {
                e.preventDefault();
                const allFileIds = displayFiles.map(f => f.id);
                const allFolderIds = showFolders ? folders?.map(f => f.id) || [] : [];
                selectAll(allFileIds, allFolderIds);
            }

            // Delete - delete selected
            if (e.key === 'Delete' && (selectedFileIds.size > 0 || selectedFolderIds.size > 0)) {
                e.preventDefault();
                const selectedFiles = displayFiles?.filter(f => selectedFileIds.has(f.id)) || [];
                const selectedFolders = folders?.filter(f => selectedFolderIds.has(f.id)) || [];
                if (selectedFiles.length > 0 || selectedFolders.length > 0) {
                    setDeleteConfirm({ type: 'multiple', items: [...selectedFiles, ...selectedFolders] });
                }
            }

            // F2 - rename selected
            if (e.key === 'F2') {
                e.preventDefault();
                if (selectedFileIds.size === 1) {
                    const file = displayFiles?.find(f => selectedFileIds.has(f.id));
                    if (file) setRenameFile(file);
                } else if (selectedFolderIds.size === 1) {
                    const folder = folders?.find(f => selectedFolderIds.has(f.id));
                    if (folder) setRenameFolder(folder);
                }
            }

            // Backspace - go to parent folder
            if (e.key === 'Backspace' && breadcrumbs.length > 1) {
                navigateToBreadcrumb(breadcrumbs.length - 2);
            }

            // Ctrl+C - Copy
            if (e.ctrlKey && e.key === 'c' && (selectedFileIds.size > 0 || selectedFolderIds.size > 0)) {
                e.preventDefault();
                const selectedFiles = displayFiles?.filter(f => selectedFileIds.has(f.id)) || [];
                const selectedFolders = folders?.filter(f => selectedFolderIds.has(f.id)) || [];
                setClipboard({ mode: 'copy', files: selectedFiles, folders: selectedFolders });
            }

            // Ctrl+X - Cut
            if (e.ctrlKey && e.key === 'x' && (selectedFileIds.size > 0 || selectedFolderIds.size > 0)) {
                e.preventDefault();
                const selectedFiles = displayFiles?.filter(f => selectedFileIds.has(f.id)) || [];
                const selectedFolders = folders?.filter(f => selectedFolderIds.has(f.id)) || [];
                setClipboard({ mode: 'cut', files: selectedFiles, folders: selectedFolders });
            }

            // Ctrl+V - Paste
            if (e.ctrlKey && e.key === 'v' && clipboard && (clipboard.files.length > 0 || clipboard.folders.length > 0)) {
                e.preventDefault();
                handlePaste();
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [
        previewFile, showNewFolder, moveItems, deleteConfirm, 
        selectedFileIds, selectedFolderIds, displayFiles, breadcrumbs, clipboard, 
        currentFolderId, handlePaste, handleRefresh,
        setPreviewFile, setShowNewFolder, setMoveItems, setDeleteConfirm, 
        clearSelection, selectAll, setRenameFile, navigateToBreadcrumb, setClipboard, folders, showFolders
    ]);

    // Keep visibleFiles in sync so store selection mutators can derive the
    // full selected file objects (not just the filtered subset).
    useEffect(() => {
        if (displayFiles) setVisibleFiles(displayFiles);
    }, [displayFiles, setVisibleFiles]);

    // Keep selectedFiles in sync with selectedFileIds
    useEffect(() => {
        const selectedFiles = displayFiles?.filter(f => selectedFileIds.has(f.id)) || [];
        setSelectedFiles(selectedFiles);
    }, [selectedFileIds, displayFiles, setSelectedFiles]);

    // Infinite scrolling
    useEffect(() => {
        const handleScroll = () => {
            // Block page bumps while a reset is pending or a page fetch is in flight
            if (containerRef.current && !isLoading && !pageLoadingRef.current && !pendingResetRef.current && hasMore && activeSection === 'files') {
                const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
                if (scrollTop + clientHeight >= scrollHeight - 100) {
                    pageLoadingRef.current = true;
                    setPage(prev => prev + 1);
                }
            }
        };

        const container = containerRef.current;
        if (container) {
            container.addEventListener('scroll', handleScroll, { passive: true });
            return () => container.removeEventListener('scroll', handleScroll);
        }
    }, [isLoading, hasMore, activeSection]);

    // Reset pagination when filters change
    useEffect(() => {
        pendingResetRef.current = true;
        pageLoadingRef.current = false;
        setPage(1);
        setAllFiles([]);
        setHasMore(true);
    }, [currentFolderId, fileTypeFilter, searchQuery, activeSection]);

    // For files section, replace on page 1 (folder/filter/search change), append with dedupe for later pages.
    // Runs after the reset effect above so a cached page-1 for the new key replaces instead of being wiped.
    useEffect(() => {
        if (activeSection !== 'files') return;
        // A failed page fetch (server error, network drop) must not leave the
        // scroll guards stuck — otherwise infinite scroll deadlocks forever and
        // the UI silently falls into the empty state. Reset them on error too.
        if (filesError) {
            pendingResetRef.current = false;
            pageLoadingRef.current = false;
            return;
        }
        if (filesList) {
            if (filesList.page <= 1) pendingResetRef.current = false;
            pageLoadingRef.current = false;
            setAllFiles(prev => {
                if (filesList.page <= 1) return filesList.files;
                const existingIds = new Set(prev.map(f => f.id));
                const newFiles = filesList.files.filter(f => !existingIds.has(f.id));
                return [...prev, ...newFiles];
            });
            setHasMore(filesList.page * filesList.per_page < filesList.total);
        }
    }, [filesList, activeSection, filesError]);

    if (showAdminPanel) {
        return <AdminPanel onBack={() => setShowAdminPanel(false)} />;
    }

    return (
        <div className="flex h-screen bg-dark-950 text-white selection:bg-primary-500/30 overflow-hidden">
            <Sidebar isOpen={isSidebarOpen} onClose={() => setSidebarOpen(false)} />
            
            <main className={`flex-1 flex flex-col min-w-0 relative bg-gradient-to-br from-dark-950 to-dark-900 transition-[margin] duration-300 ease-in-out ${isSidebarOpen ? 'md:ml-64' : 'ml-0'}`}>
                {/* Header */}
                <header className="h-16 border-b border-white/[0.06] flex items-center justify-between px-4 sm:px-6 bg-dark-900/50 backdrop-blur-sm z-30 sticky top-0">
                    {/* Left: Hamburger & Search & Breadcrumbs */}
                    <div className="flex items-center gap-3 md:gap-6 flex-1 min-w-0">
                        {/* Hamburger */}
                        <button 
                            onClick={() => setSidebarOpen(!isSidebarOpen)}
                            className="p-2 -ml-2 text-dark-400 hover:text-white"
                        >
                            <Menu className="w-6 h-6" />
                        </button>

                        {/* Search */}
                        <div className="relative w-full max-w-[200px] sm:max-w-xs md:w-64">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dark-500" />
<input
                                    type="text"
                                    placeholder="Search..."
                                    value={searchInput}
                                    onChange={(e) => setSearchInput(e.target.value)}
                                    className="w-full bg-dark-800/50 border border-white/[0.06] rounded-lg pl-9 pr-3 py-1.5 text-sm text-white focus:outline-none focus:border-primary-500/50 focus:bg-dark-800 transition-all"
                                />
                        </div>
                        
                        {/* Vertical Div */}
                        <div className="hidden sm:block w-px h-6 bg-white/[0.1]"></div>

                        {/* Breadcrumbs */}
                        <nav className="flex items-center gap-0.5 overflow-hidden hidden sm:flex">
                            {breadcrumbs.map((crumb, index) => (
                                <div key={crumb.id || 'root'} className="flex items-center min-w-0">
                                    {index > 0 && <ChevronRight className="w-4 h-4 text-dark-600 mx-1 shrink-0" />}
                                    <button 
                                        onClick={() => navigateToBreadcrumb(index)}
                                        className={`px-2 py-1 rounded-md text-sm truncate max-w-[150px] transition-colors ${index === breadcrumbs.length - 1 
                                            ? 'text-white font-medium bg-white/[0.05]'
                                            : 'text-dark-400 hover:text-white hover:bg-white/[0.05]'
                                            }`}
                                    >
                                        {index === 0 && <Home className="w-3.5 h-3.5" />}
                                        {crumb.name}
                                    </button>
                                </div>
                            ))}
                        </nav>
                    </div>

                    {/* Right: Actions */}
                    <div className="flex items-center gap-2 sm:gap-3">
                         {/* Filter buttons with Icons */}
                        <div className="hidden md:flex items-center bg-dark-800/50 rounded-lg p-0.5 border border-white/[0.06] mr-2">
                             <button
                                onClick={() => setFileTypeFilter(null)}
                                title="All Files"
                                className={`p-1.5 rounded-md transition-all ${
                                    !fileTypeFilter ? 'bg-primary-600 text-white shadow-sm' : 'text-dark-400 hover:text-white hover:bg-white/[0.05]'
                                }`}
                            >
                                <Grid className="w-4 h-4" />
                            </button>
                            <button
                                onClick={() => setFileTypeFilter('video')}
                                title="Videos"
                                className={`p-1.5 rounded-md transition-all ${
                                    fileTypeFilter === 'video' ? 'bg-primary-600 text-white shadow-sm' : 'text-dark-400 hover:text-white hover:bg-white/[0.05]'
                                }`}
                            >
                                <Film className="w-4 h-4" />
                            </button>
                            <button
                                onClick={() => setFileTypeFilter('audio')}
                                title="Audio"
                                className={`p-1.5 rounded-md transition-all ${
                                    fileTypeFilter === 'audio' ? 'bg-primary-600 text-white shadow-sm' : 'text-dark-400 hover:text-white hover:bg-white/[0.05]'
                                }`}
                            >
                                <Music className="w-4 h-4" />
                            </button>
                            <button
                                onClick={() => setFileTypeFilter('image')}
                                title="Images"
                                className={`p-1.5 rounded-md transition-all ${
                                    fileTypeFilter === 'image' ? 'bg-primary-600 text-white shadow-sm' : 'text-dark-400 hover:text-white hover:bg-white/[0.05]'
                                }`}
                            >
                                <ImageIcon className="w-4 h-4" />
                            </button>
                            <button
                                onClick={() => setFileTypeFilter('document')}
                                title="Documents"
                                className={`p-1.5 rounded-md transition-all ${
                                    fileTypeFilter === 'document' ? 'bg-primary-600 text-white shadow-sm' : 'text-dark-400 hover:text-white hover:bg-white/[0.05]'
                                }`}
                            >
                                <FileText className="w-4 h-4" />
                            </button>
                        </div>
 
                         <div className="flex items-center gap-1 bg-dark-800/50 rounded-lg p-0.5 border border-white/[0.06]">
                             <button
                                 onClick={handleRefresh}
                                 disabled={isLoading}
                                 className={`p-1.5 rounded-md text-dark-400 hover:text-white hover:bg-white/[0.05] transition-all active:scale-95 ${isLoading ? 'animate-spin' : ''}`}
                                 title="Refresh"
                             >
                                 <RefreshCw className="w-4 h-4" />
                             </button>
                             <div className="w-px h-3 bg-white/[0.1] mx-1"></div>
                             <button
                                 onClick={() => setViewMode('grid')}
                                 className={`p-1.5 rounded-md transition-all ${viewMode === 'grid' ? 'bg-primary-600 text-white shadow-sm' : 'text-dark-400 hover:text-white hover:bg-white/[0.05]'}`}
                             >
                                 <Grid className="w-4 h-4" />
                             </button>
                             <button
                                 onClick={() => setViewMode('list')}
                                 className={`p-1.5 rounded-md transition-all ${viewMode === 'list' ? 'bg-primary-600 text-white shadow-sm' : 'text-dark-400 hover:text-white hover:bg-white/[0.05]'}`}
                             >
                                 <List className="w-4 h-4" />
                             </button>
                         </div>


                        {clipboard && (clipboard.files.length > 0 || clipboard.folders.length > 0) && (
                            <button
                                onClick={handlePaste}
                                className="ml-2 btn-secondary py-1.5 px-3 text-xs flex items-center gap-2 bg-primary-500/10 text-primary-300 border-primary-500/20 hover:bg-primary-500/20"
                            >
                                <Clipboard className="w-3.5 h-3.5" />
                                Paste ({clipboard.files.length + clipboard.folders.length})
                            </button>
                        )}

                        {activeSection === 'files' && (
                            <button
                                onClick={() => setShowNewFolder(true)}
                                className="ml-2 btn-primary py-1.5 px-3 text-sm flex items-center gap-2 shadow-lg shadow-primary-500/20"
                            >
                                <FolderPlus className="w-4 h-4" />
                                <span className="hidden sm:inline">New Folder</span>
                            </button>
                        )}
                    </div>
                </header>

                {/* Content Area */}
                <div 
                    ref={containerRef}
                    className="flex-1 overflow-auto p-6 relative outline-none"
                    onMouseDown={handleMouseDown}
                    onMouseMove={handleMouseMove}
                    onMouseUp={handleMouseUp}
                    onMouseLeave={handleMouseUp}
                    tabIndex={0}
                    // Prevent default drag behaviors on container
                    onDragOver={(e) => e.preventDefault()}
                >
                    {activeSection === 'grab' ? (
<GrabSearch />
                    ) : isLoading && !displayFiles?.length ? (
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 animate-fade-in">
                            {[...Array(10)].map((_, i) => (
                                <div key={i} className="aspect-video bg-dark-800/50 rounded-xl animate-pulse"></div>
                            ))}
                        </div>
                    ) : (
                        <>
                             {/* Unified View */}
                             {(showFolders && folders?.length ? folders.length : 0) + (displayFiles?.length || 0) > 0 ? (
                                <div className={viewMode === 'grid'
                                    ? 'grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3 sm:gap-4 pb-20'
                                    : 'flex flex-col gap-2 pb-20'
                                }>
                                    {/* Folders */}
                                    {showFolders && folders?.map((folder) => (
                                        <FolderCard
                                            key={folder.id}
                                            folder={folder}
                                            viewMode={viewMode}
                                            selected={selectedFolderIds.has(folder.id)}
                                            onSelect={(multi) => selectFolder(folder.id, multi)}
                                            onOpen={() => navigateToFolder(folder)}
                                            onFileDrop={handleFileDrop}
                                        />
                                    ))}
                                    
                                    {/* Files */}
                                    {displayFiles?.map((file) => (
                                        <FileCard
                                            key={file.id}
                                            file={file}
                                            viewMode={viewMode}
                                            selected={selectedFileIds.has(file.id)}
                                            onSelect={(multi) => selectFile(file.id, multi)}
                                            onPlay={() => handleFileOpen(file)}
                                        />
                                    ))}
                                </div>
                            ) : (
                                <div className="h-full flex flex-col items-center justify-center text-center pb-20 animate-fade-in">
                                    <div className="w-24 h-24 rounded-3xl bg-dark-800/50 flex items-center justify-center border border-white/[0.04] mb-6 shadow-2xl">
                                        <ArrowUp className="w-10 h-10 text-dark-600 animate-bounce" />
                                    </div>
                                    <h3 className="text-xl font-bold text-white mb-2">No files found</h3>
                                    <p className="text-dark-400 max-w-xs">
                                        Upload files by sending them to the Telegram bot
                                    </p>
                                </div>
                            )}

                            {/* Selection Rectangle Overlay */}
                            {selectionBox?.active && (
                                <div 
                                    className="absolute bg-primary-500/10 border border-primary-500/30 pointer-events-none rounded sm z-50 backdrop-blur-[1px]"
                                    style={{
                                        left: Math.min(selectionBox.x1, selectionBox.x2),
                                        top: Math.min(selectionBox.y1, selectionBox.y2),
                                        width: Math.abs(selectionBox.x1 - selectionBox.x2),
                                        height: Math.abs(selectionBox.y1 - selectionBox.y2),
                                    }}
                                />
                            )}
                        </>
                    )}

                    {/* Loading indicator for infinite scroll */}
                    {activeSection === 'files' && isLoading && hasMore && (
                        <div className="flex justify-center py-4">
                            <div className="w-6 h-6 border-2 border-primary-500/30 border-t-primary-500 rounded-full animate-spin"></div>
                        </div>
                    )}

                    {/* No more files message */}
                    {activeSection === 'files' && !hasMore && allFiles.length > 0 && (
                        <div className="text-center py-4 text-dark-400">
                            No more files
                        </div>
                    )}
                </div>
            </main>
            
            <Toasts />

            {/* Modals */}
            {showNewFolder && (
                <NewFolderModal
                    parentId={currentFolderId}
                    onClose={() => setShowNewFolder(false)}
                />
            )}

                {moveItems && (
                    <MoveFileModal
                        items={moveItems}
                        onClose={() => setMoveItems(null)}
                    />
                )}

            {deleteConfirm && (
                <DeleteConfirmModal
                    type={deleteConfirm.type}
                    count={deleteConfirm.items.length}
                    name={deleteConfirm.items.length === 1 
                        ? (deleteConfirm.type === 'file' ? (deleteConfirm.items[0] as TelegramFile).file_name : (deleteConfirm.items[0] as Folder).name)
                        : undefined
                    }
                    onConfirm={handleDeleteConfirm}
                    onClose={() => setDeleteConfirm(null)}
                />
            )}

            {/* Rename modals */}
            <RenameModal
                isOpen={!!renameFile}
                onClose={() => setRenameFile(null)}
                onRename={handleRenameFile}
                currentName={renameFile?.file_name || ''}
                itemType="file"
            />

            <RenameModal
                isOpen={!!renameFolder}
                onClose={() => setRenameFolder(null)}
                onRename={handleRenameFolder}
                currentName={renameFolder?.name || ''}
                itemType="folder"
            />
        </div>
    );
}
