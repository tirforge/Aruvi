/**
 * RenameModal - Modal for renaming files and folders
 */
import { useState, useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { useAppStore } from '../lib/store';

interface RenameModalProps {
    isOpen: boolean;
    onClose: () => void;
    onRename: (newName: string) => void | Promise<void>;
    currentName: string;
    itemType: 'file' | 'folder';
}

function errorMessage(err: any, fallback: string) {
    const detail = err?.response?.data?.detail;
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg).join(', ');
    return detail || fallback;
}

export default function RenameModal({ isOpen, onClose, onRename, currentName, itemType }: RenameModalProps) {
    const [name, setName] = useState(currentName);
    const inputRef = useRef<HTMLInputElement>(null);
    const [isPending, setIsPending] = useState(false);
    const addToast = useAppStore((s) => s.addToast);
    // This component stays mounted and toggles via isOpen, so an unmount
    // hook can't restore focus — track the open transition instead.
    const wasOpenRef = useRef(false);
    const openerRef = useRef<HTMLElement | null>(null);
    const focusTimerRef = useRef<number | null>(null);

    // NOTE: FileBrowser passes inline onClose arrows, so effects depending on
    // onClose would re-run every parent render. The two effects below depend
    // on isOpen only and read the other props via refs/at-open snapshot.
    useEffect(() => {
        if (isOpen && !wasOpenRef.current) {
            // Opening: snapshot the opener, seed the name ONCE, focus input.
            // (The old effect re-ran on every currentName change and wiped
            // mid-edit typing when renameFile/renameFolder flipped A→B.)
            wasOpenRef.current = true;
            openerRef.current = document.activeElement as HTMLElement | null;
            // Snapshot props at open; later parent re-renders must not clobber.
            setName(currentName);
            const snapName = currentName;
            const snapType = itemType;
            focusTimerRef.current = window.setTimeout(() => {
                focusTimerRef.current = null;
                if (inputRef.current) {
                    inputRef.current.focus();
                    // Select filename without extension for files
                    if (snapType === 'file') {
                        const lastDot = snapName.lastIndexOf('.');
                        if (lastDot > 0) {
                            inputRef.current.setSelectionRange(0, lastDot);
                        } else {
                            inputRef.current.select();
                        }
                    } else {
                        inputRef.current.select();
                    }
                }
            }, 50);
        }
        if (!isOpen && wasOpenRef.current) {
            // Closed: hand focus back to the invoking Rename button so
            // keyboard users don't drop to <body>.
            wasOpenRef.current = false;
            try { openerRef.current?.focus?.({ preventScroll: true }); } catch { /* noop */ }
        }
        // Clear a pending focus timer whenever the effect re-runs or the
        // component unmounts — focusing an unmounted input throws.
        return () => {
            if (focusTimerRef.current !== null) {
                clearTimeout(focusTimerRef.current);
                focusTimerRef.current = null;
            }
        };
    }, [isOpen]);

    // Escape closes the modal. Separate effect: the open-transition effect
    // above must not re-subscribe on every parent render (inline onClose).
    // Guarded while the rename POST is in flight — closing mid-mutation
    // confuses (the rename still completes + toasts, so the close looks
    // like a cancel that wasn't).
    const onCloseRef = useRef(onClose);
    onCloseRef.current = onClose;
    const isPendingRef = useRef(isPending);
    isPendingRef.current = isPending;
    const safeClose = () => { if (!isPendingRef.current) onCloseRef.current(); };
    useEffect(() => {
        if (!isOpen) return;
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                safeClose();
            }
        };
        document.addEventListener('keydown', handleEscape);
        return () => document.removeEventListener('keydown', handleEscape);
    }, [isOpen]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const trimmed = name.trim();
        if (!trimmed) return;
        if (trimmed === currentName) {
            onClose();
            return;
        }
        setIsPending(true);
        try {
            await onRename(trimmed);
            onClose();
        } catch (error) {
            addToast(errorMessage(error, 'Failed to rename'), 'error');
        } finally {
            setIsPending(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div
            onClick={(e) => { if (e.target === e.currentTarget) safeClose(); }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in">
            <div className="bg-dark-800 rounded-xl border border-dark-600 p-6 w-full max-w-md shadow-2xl">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                        Rename {itemType === 'file' ? 'File' : 'Folder'}
                    </h2>
                    <button onClick={safeClose} className="text-dark-400 hover:text-white transition-colors">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <form onSubmit={handleSubmit}>
                    <input
                        ref={inputRef}
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className="w-full px-4 py-3 bg-dark-700 border border-dark-600 rounded-lg text-white placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                        placeholder={`Enter ${itemType} name`}
                    />

                    <div className="flex gap-3 mt-6">
                        <button
                            type="button"
                            onClick={safeClose}
                            className="flex-1 px-4 py-2 bg-dark-700 hover:bg-dark-600 text-white rounded-lg transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={!name.trim() || name.trim() === currentName || isPending}
                            className="flex-1 px-4 py-2 bg-primary-600 hover:bg-primary-500 disabled:bg-dark-600 disabled:text-dark-400 text-white rounded-lg transition-colors"
                        >
                            {isPending ? 'Renaming...' : 'Rename'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
