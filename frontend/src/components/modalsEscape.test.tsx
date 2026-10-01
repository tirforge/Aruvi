/**
 * Modal Escape behavior.
 *
 * Each modal owns its keydown listener so FileBrowser's global handler
 * can't double-close or bypass the in-flight guard. The modal must stop
 * propagation (a window-level listener must never see the event) and
 * close exactly once. Non-Escape keys must not close. While a mutation
 * is in flight, Escape must NOT close (the mutation still completes).
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent, cleanup, screen, type RenderResult } from '@testing-library/react';
import DeleteConfirmModal from './DeleteConfirmModal';
import MoveFileModal from './MoveFileModal';
import NewFolderModal from './NewFolderModal';
import RenameModal from './RenameModal';

// Unit under test is the Escape wiring, not data fetching.
// Pending flags are hoisted so tests can flip move/create into pending.
const pendingState = vi.hoisted(() => ({
    moveFiles: false,
    moveFolders: false,
    createFolder: false,
}));

vi.mock('../lib/api', () => ({
    useFolderTree: () => ({ data: [], isLoading: false }),
    useMoveFiles: () => ({ mutateAsync: vi.fn(), isPending: pendingState.moveFiles }),
    useMoveFolders: () => ({ mutateAsync: vi.fn(), isPending: pendingState.moveFolders }),
    useCreateFolder: () => ({ mutateAsync: vi.fn(), isPending: pendingState.createFolder }),
}));

afterEach(() => {
    cleanup();
    pendingState.moveFiles = false;
    pendingState.moveFolders = false;
    pendingState.createFolder = false;
});

/** Press a key on the modal backdrop; report window-level listeners hit. */
function pressOnBackdrop(container: HTMLElement, key: string) {
    const backdrop = container.firstElementChild as HTMLElement;
    const windowSpy = vi.fn();
    window.addEventListener('keydown', windowSpy);
    fireEvent.keyDown(backdrop, { key });
    window.removeEventListener('keydown', windowSpy);
    return windowSpy;
}

function expectEscapeClosesOnce(renderModal: (onClose: () => void) => RenderResult) {
    const onClose = vi.fn();
    const { container } = renderModal(onClose);
    const windowSpy = pressOnBackdrop(container, 'Escape');
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(windowSpy).not.toHaveBeenCalled();
}

function expectOtherKeysIgnored(renderModal: (onClose: () => void) => RenderResult) {
    const onClose = vi.fn();
    const { container } = renderModal(onClose);
    pressOnBackdrop(container, 'Enter');
    expect(onClose).not.toHaveBeenCalled();
}

function expectEscapeBlockedWhilePending(container: HTMLElement, onClose: ReturnType<typeof vi.fn>) {
    const windowSpy = pressOnBackdrop(container, 'Escape');
    expect(onClose).not.toHaveBeenCalled();
    expect(windowSpy).not.toHaveBeenCalled();
}

describe('DeleteConfirmModal', () => {
    const renderModal = (onClose: () => void) =>
        render(
            <DeleteConfirmModal type="file" name="old.txt" onConfirm={() => {}} onClose={onClose} />,
        );
    it('Escape stops propagation and closes exactly once', () => expectEscapeClosesOnce(renderModal));
    it('ignores non-Escape keys', () => expectOtherKeysIgnored(renderModal));
    it('Escape does not close while delete is in flight', async () => {
        const onClose = vi.fn();
        const { container } = render(
            <DeleteConfirmModal
                type="file"
                name="old.txt"
                onConfirm={() => new Promise<void>(() => {})}
                onClose={onClose}
            />,
        );
        fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
        await screen.findByText('Deleting...');
        expectEscapeBlockedWhilePending(container, onClose);
    });
});

describe('MoveFileModal', () => {
    const renderModal = (onClose: () => void) =>
        render(<MoveFileModal items={{ files: [], folders: [] }} onClose={onClose} />);
    it('Escape stops propagation and closes exactly once', () => expectEscapeClosesOnce(renderModal));
    it('ignores non-Escape keys', () => expectOtherKeysIgnored(renderModal));
    it('Escape does not close while move is pending', () => {
        pendingState.moveFiles = true;
        pendingState.moveFolders = true;
        const onClose = vi.fn();
        const { container } = render(
            <MoveFileModal items={{ files: [], folders: [] }} onClose={onClose} />,
        );
        expectEscapeBlockedWhilePending(container, onClose);
    });
});

describe('NewFolderModal', () => {
    const renderModal = (onClose: () => void) =>
        render(<NewFolderModal parentId={null} onClose={onClose} />);
    it('Escape stops propagation and closes exactly once', () => expectEscapeClosesOnce(renderModal));
    it('ignores non-Escape keys', () => expectOtherKeysIgnored(renderModal));
    it('Escape does not close while create is pending', () => {
        pendingState.createFolder = true;
        const onClose = vi.fn();
        const { container } = render(<NewFolderModal parentId={null} onClose={onClose} />);
        expectEscapeBlockedWhilePending(container, onClose);
    });
});

describe('RenameModal', () => {
    const renderModal = (onClose: () => void) =>
        render(
            <RenameModal
                isOpen
                onClose={onClose}
                onRename={() => {}}
                currentName="old.txt"
                itemType="file"
            />,
        );
    it('Escape stops propagation and closes exactly once', () => expectEscapeClosesOnce(renderModal));
    it('ignores non-Escape keys', () => expectOtherKeysIgnored(renderModal));
    it('Escape does not close while rename is in flight', async () => {
        const onClose = vi.fn();
        const { container } = render(
            <RenameModal
                isOpen
                onClose={onClose}
                onRename={() => new Promise<void>(() => {})}
                currentName="old.txt"
                itemType="file"
            />,
        );
        fireEvent.change(screen.getByPlaceholderText('Enter file name'), {
            target: { value: 'new.txt' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
        await screen.findByText('Renaming...');
        expectEscapeBlockedWhilePending(container, onClose);
    });
});
