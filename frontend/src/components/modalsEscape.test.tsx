/**
 * Modal Escape behavior.
 *
 * Each modal owns its keydown listener so FileBrowser's global handler
 * can't double-close or bypass the in-flight guard. The modal must stop
 * propagation (a window-level listener must never see the event) and
 * close exactly once. Non-Escape keys must not close.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent, cleanup, type RenderResult } from '@testing-library/react';
import DeleteConfirmModal from './DeleteConfirmModal';
import MoveFileModal from './MoveFileModal';
import NewFolderModal from './NewFolderModal';
import RenameModal from './RenameModal';

// Unit under test is the Escape wiring, not data fetching.
vi.mock('../lib/api', () => ({
    useFolderTree: () => ({ data: [], isLoading: false }),
    useMoveFiles: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useMoveFolders: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useCreateFolder: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

afterEach(cleanup);

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

describe('DeleteConfirmModal', () => {
    const renderModal = (onClose: () => void) =>
        render(
            <DeleteConfirmModal type="file" name="old.txt" onConfirm={() => {}} onClose={onClose} />,
        );
    it('Escape stops propagation and closes exactly once', () => expectEscapeClosesOnce(renderModal));
    it('ignores non-Escape keys', () => expectOtherKeysIgnored(renderModal));
});

describe('MoveFileModal', () => {
    const renderModal = (onClose: () => void) =>
        render(<MoveFileModal items={{ files: [], folders: [] }} onClose={onClose} />);
    it('Escape stops propagation and closes exactly once', () => expectEscapeClosesOnce(renderModal));
    it('ignores non-Escape keys', () => expectOtherKeysIgnored(renderModal));
});

describe('NewFolderModal', () => {
    const renderModal = (onClose: () => void) =>
        render(<NewFolderModal parentId={null} onClose={onClose} />);
    it('Escape stops propagation and closes exactly once', () => expectEscapeClosesOnce(renderModal));
    it('ignores non-Escape keys', () => expectOtherKeysIgnored(renderModal));
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
});
