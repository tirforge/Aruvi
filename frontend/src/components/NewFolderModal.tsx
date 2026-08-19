/**
 * NewFolderModal - modal for creating a new folder
 */
import { useState } from 'react';
import { X, FolderPlus } from 'lucide-react';
import { useCreateFolder } from '../lib/api';
import { useAppStore } from '../lib/store';

interface NewFolderModalProps {
    parentId: number | null;
    onClose: () => void;
}

function errorMessage(err: any, fallback: string) {
    const detail = err?.response?.data?.detail;
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg).join(', ');
    return detail || fallback;
}

export default function NewFolderModal({ parentId, onClose }: NewFolderModalProps) {
    const [name, setName] = useState('');
    const createFolder = useCreateFolder();
    const addToast = useAppStore((s) => s.addToast);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim()) return;

        try {
            await createFolder.mutateAsync({
                name: name.trim(),
                parent_id: parentId,
            });
            onClose();
        } catch (error) {
            addToast(errorMessage(error, 'Failed to create folder'), 'error');
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
            <div className="glass-card w-full max-w-md p-6 animate-slide-up">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold flex items-center gap-2">
                        <FolderPlus className="w-5 h-5 text-primary-400" />
                        New Folder
                    </h2>
                    <button onClick={onClose} className="p-1 hover:bg-dark-700 rounded">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <form onSubmit={handleSubmit}>
                    <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Folder name"
                        autoFocus
                        className="w-full px-4 py-3 bg-dark-700 border border-dark-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500/50 mb-4"
                    />

                    <div className="flex justify-end gap-3">
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-4 py-2 text-dark-400 hover:text-white transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={!name.trim() || createFolder.isPending}
                            className="px-4 py-2 bg-primary-600 hover:bg-primary-700 rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            {createFolder.isPending ? 'Creating...' : 'Create'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
