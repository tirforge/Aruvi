/**
 * AppState management using Zustand
 */
import { create } from 'zustand';
import { TelegramFile, Folder } from './api';

interface AppState {
    // Current navigation
    currentFolderId: number | null;
    setCurrentFolderId: (id: number | null) => void;

    // Breadcrumb path
    breadcrumbs: Array<{ id: number | null; name: string }>;
    setBreadcrumbs: (breadcrumbs: Array<{ id: number | null; name: string }>) => void;

    // The currently visible file list (used to derive selectedFiles from ids).
    visibleFiles: TelegramFile[];
    setVisibleFiles: (files: TelegramFile[]) => void;

    // Selection
    selectedFileIds: Set<number>;
    selectedFolderIds: Set<number>;
    selectFile: (id: number, multi?: boolean) => void;
    deselectFile: (id: number) => void;
    selectFolder: (id: number, multi?: boolean) => void;
    deselectFolder: (id: number) => void;
    clearSelection: () => void;
    selectAll: (fileIds: number[], folderIds?: number[]) => void;

    // View mode
    viewMode: 'grid' | 'list';
    setViewMode: (mode: 'grid' | 'list') => void;

    // Modals
    previewFile: TelegramFile | null;
    setPreviewFile: (file: TelegramFile | null) => void;

    renameFile: TelegramFile | null;
    setRenameFile: (file: TelegramFile | null) => void;

    renameFolder: Folder | null;
    setRenameFolder: (folder: Folder | null) => void;

    moveItems: { files: TelegramFile[], folders: Folder[] } | null;
    setMoveItems: (items: { files: TelegramFile[], folders: Folder[] } | null) => void;
    setMoveFiles: (files: TelegramFile[]) => void;

    showNewFolder: boolean;
    setShowNewFolder: (show: boolean) => void;

    deleteConfirm: { type: 'file' | 'folder' | 'multiple'; items: (TelegramFile | Folder)[] } | null;
    setDeleteConfirm: (item: { type: 'file' | 'folder' | 'multiple'; items: (TelegramFile | Folder)[] } | null) => void;

    // Clipboard
    clipboard: { mode: 'copy' | 'cut'; files: TelegramFile[]; folders: Folder[] } | null;
    setClipboard: (clipboard: { mode: 'copy' | 'cut'; files: TelegramFile[]; folders: Folder[] } | null) => void;

    // Player state
    isPlayerMinimized: boolean;
    setPlayerMinimized: (minimized: boolean) => void;

    // Search
    searchQuery: string;
    setSearchQuery: (query: string) => void;

    // Filter
    fileTypeFilter: string | null;
    setFileTypeFilter: (type: string | null) => void;

    // Context menu - only one can be open at a time, with position for fixed positioning
    activeContextMenu: { type: 'file'; item: TelegramFile; x: number; y: number } | { type: 'folder'; item: Folder; x: number; y: number } | null;
    setActiveContextMenu: (menu: { type: 'file'; item: TelegramFile; x: number; y: number } | { type: 'folder'; item: Folder; x: number; y: number } | null) => void;
    selectedFiles: TelegramFile[];
    setSelectedFiles: (files: TelegramFile[]) => void;

    // Navigation Section
    activeSection: 'files' | 'recent' | 'continue_watching' | 'grab';
    setActiveSection: (section: 'files' | 'recent' | 'continue_watching' | 'grab') => void;

    // Admin Panel
    showAdminPanel: boolean;
    setShowAdminPanel: (show: boolean) => void;

    // Toast Notifications
    toasts: Array<{ id: string; message: string; type: 'success' | 'error' | 'info' }>;
    addToast: (message: string, type?: 'success' | 'error' | 'info') => void;
    removeToast: (id: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
    // Navigation
    currentFolderId: null,
    setCurrentFolderId: (id) => set({ currentFolderId: id }),
    breadcrumbs: [{ id: null, name: 'My Files' }],
    setBreadcrumbs: (breadcrumbs) => set({ breadcrumbs }),

    // Navigation Section
    activeSection: 'files',
    setActiveSection: (section) => set({ activeSection: section, showAdminPanel: false, currentFolderId: null, breadcrumbs: [{ id: null, name: section === 'files' ? 'My Files' : section === 'recent' ? 'Recently Added' : section === 'grab' ? 'Search Movies' : 'Continue Watching' }] }),

    // Admin Panel
    showAdminPanel: false,
    setShowAdminPanel: (show) => set({ showAdminPanel: show }),

    // Selection
    selectedFileIds: new Set(),
    selectedFolderIds: new Set(),
    visibleFiles: [],
    setVisibleFiles: (files) => set({ visibleFiles: files }),
    selectFile: (id, multi = false) => set((state) => {
        if (multi) {
            const newSet = new Set(state.selectedFileIds);
            if (newSet.has(id)) newSet.delete(id);
            else newSet.add(id);
            return {
                selectedFileIds: newSet,
                selectedFiles: state.visibleFiles.filter((f) => newSet.has(f.id)),
            };
        }
        return {
            selectedFileIds: new Set([id]),
            selectedFolderIds: new Set(),
            selectedFiles: state.visibleFiles.filter((f) => f.id === id),
        };
    }),
    deselectFile: (id) => set((state) => {
        const newSet = new Set(state.selectedFileIds);
        newSet.delete(id);
        return {
            selectedFileIds: newSet,
            selectedFiles: state.selectedFiles.filter((f) => f.id !== id),
        };
    }),
    selectFolder: (id, multi = false) => set((state) => {
        if (multi) {
            const newSet = new Set(state.selectedFolderIds);
            if (newSet.has(id)) newSet.delete(id);
            else newSet.add(id);
            return { selectedFolderIds: newSet };
        }
        return {
            selectedFolderIds: new Set([id]),
            selectedFileIds: new Set(),
            selectedFiles: [],
        };
    }),
    deselectFolder: (id) => set((state) => {
        const newSet = new Set(state.selectedFolderIds);
        newSet.delete(id);
        return { selectedFolderIds: newSet };
    }),
    clearSelection: () => set({ selectedFileIds: new Set(), selectedFolderIds: new Set(), selectedFiles: [] }),
    selectAll: (fileIds, folderIds = []) => set((state) => ({
        selectedFileIds: new Set(fileIds),
        selectedFolderIds: new Set(folderIds),
        selectedFiles: state.visibleFiles.filter((f) => fileIds.includes(f.id)),
    })),

    // View mode
    viewMode: 'grid',
    setViewMode: (mode) => set({ viewMode: mode }),

    // Modals
    previewFile: null,
    setPreviewFile: (file) => set({ previewFile: file }),

    renameFile: null,
    setRenameFile: (file) => set({ renameFile: file }),

    renameFolder: null,
    setRenameFolder: (folder) => set({ renameFolder: folder }),

    moveItems: null,
    setMoveItems: (items) => set({ moveItems: items }),
    setMoveFiles: (files) => set({ moveItems: { files, folders: [] } }),
    selectedFiles: [],
    setSelectedFiles: (files) => set({ selectedFiles: files }),

    showNewFolder: false,
    setShowNewFolder: (show) => set({ showNewFolder: show }),

    deleteConfirm: null,
    setDeleteConfirm: (item) => set({ deleteConfirm: item }),

    // Clipboard
    clipboard: null,
    setClipboard: (clipboard) => set({ clipboard }),

    // Player state
    isPlayerMinimized: false,
    setPlayerMinimized: (minimized) => set({ isPlayerMinimized: minimized }),

    // Search
    searchQuery: '',
    setSearchQuery: (query) => set({ searchQuery: query }),

    // Filter
    fileTypeFilter: null,
    setFileTypeFilter: (type) => set({ fileTypeFilter: type }),

    // Context menu - only one can be open at a time
    activeContextMenu: null,
    setActiveContextMenu: (menu) => set({ activeContextMenu: menu }),

    // Toast Notifications
    toasts: [],
    addToast: (message, type = 'success') => set((state) => {
        const id = Math.random().toString(36).substring(2, 9);
        return { toasts: [...state.toasts, { id, message, type }] };
    }),
    removeToast: (id) => set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
    })),

    // Drag Selection Box
}));
