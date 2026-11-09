import { useEffect, useRef, useState } from 'react';
import { Folder, RefreshCw, Trash2, Upload } from 'lucide-react';
import { DropZone } from './DropZone';
import type { PickerMessage } from './DocumentPicker';
import {
  buildCodebaseSelection,
  entriesFromInput,
  readDroppedItems,
  supportsFolderPicker,
  type CodebaseSelection,
} from '../../lib/folderSelection';
import { formatBytes, plural } from '../../lib/format';
import { LanguageBar } from '../../components/LanguageBar';

const folderAttributes = { webkitdirectory: '', directory: '' } as Record<string, string>;

export function FolderPicker({
  selection,
  disabled,
  onSelect,
  onRemove,
  onMessage,
}: {
  selection: CodebaseSelection | null;
  disabled: boolean;
  onSelect: (selection: CodebaseSelection) => void;
  onRemove: () => void;
  onMessage: (message: PickerMessage) => void;
}) {
  const folderInput = useRef<HTMLInputElement>(null);
  const filesInput = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState(false);
  const canPickFolders = supportsFolderPicker();
  // Reading a dropped folder can be slow. Each drop takes a new number and only the latest
  // may report back; leaving the picker invalidates them all. (The pick buttons are
  // disabled while a drop is read, so a pick can't overlap one.)
  const latestRead = useRef(0);
  useEffect(
    () => () => {
      latestRead.current += 1;
    },
    [],
  );

  const finish = (result: ReturnType<typeof buildCodebaseSelection>) => {
    if (!result.ok) {
      onMessage({ tone: 'error', text: result.error });
      return;
    }
    onSelect(result.selection);
    onMessage(result.warning ? { tone: 'warning', text: result.warning } : null);
  };

  const fromInput = (files: File[]) => {
    if (files.length === 0) return; // picker cancelled
    const { entries, fromFolder } = entriesFromInput(files);
    finish(buildCodebaseSelection(entries, { fromFolder }));
  };

  const handleDrop = (dataTransfer: DataTransfer) => {
    if (disabled) return;
    const read = ++latestRead.current;
    const current = () => read === latestRead.current;
    setReading(true);
    readDroppedItems(dataTransfer)
      .then((dropped) => {
        if (!current()) return;
        finish(
          buildCodebaseSelection(dropped.entries, {
            fromFolder: dropped.hasDirectory,
            ignoredCount: dropped.ignoredCount,
            truncated: dropped.truncated,
          }),
        );
      })
      .catch(() => {
        if (current()) onMessage({ tone: 'error', text: 'DockBrain couldn’t read that folder. Try choosing it with the button instead.' });
      })
      .finally(() => {
        if (current()) setReading(false);
      });
  };

  const inputs = (
    <>
      <input
        ref={folderInput}
        type="file"
        multiple
        {...folderAttributes}
        className="visually-hidden"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="folder-input"
        onChange={(event) => {
          fromInput(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />
      <input
        ref={filesInput}
        type="file"
        multiple
        className="visually-hidden"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="files-input"
        onChange={(event) => {
          fromInput(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />
    </>
  );

  const pickFolder = () => (canPickFolders ? folderInput : filesInput).current?.click();

  if (selection) {
    return (
      <div className="picker">
        {inputs}
        <div className="selected">
          <span className="selected__icon" aria-hidden="true">
            <Folder />
          </span>
          <div className="selected__text">
            <p className="selected__name" title={selection.name}>
              {selection.name}
            </p>
            <p className="selected__meta">
              {plural(selection.files.length, 'file')} · {formatBytes(selection.totalBytes)} · selected on this device
            </p>
          </div>
          <div className="selected__actions">
            <button type="button" className="btn btn--secondary btn--sm" onClick={pickFolder} disabled={disabled}>
              <RefreshCw aria-hidden="true" />
              Replace
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={onRemove}
              disabled={disabled}
              aria-label={`Remove ${selection.name}`}
            >
              <Trash2 aria-hidden="true" />
              Remove
            </button>
          </div>
        </div>
        {selection.languages.length > 0 && <LanguageBar languages={selection.languages} />}
        {selection.ignoredCount > 0 && (
          <p className="picker__footnote">
            Left out {plural(selection.ignoredCount, 'item')} in dependency or build folders, such as node_modules
            and .git.
          </p>
        )}
        {!selection.fromFolder && (
          <p className="picker__footnote">These are individual files, so folder structure isn’t available.</p>
        )}
      </div>
    );
  }

  return (
    <div className="picker">
      {inputs}
      <DropZone onDrop={handleDrop} label="Drop a project folder here">
        <span className="dropzone__icon" aria-hidden="true">
          {reading ? <span className="spinner" /> : <Upload />}
        </span>
        <p className="dropzone__title">{reading ? 'Reading folder…' : 'Drag a project folder here'}</p>
        <p className="dropzone__hint">Dependency and build folders like node_modules are left out automatically.</p>
        <button type="button" className="btn btn--primary" onClick={pickFolder} disabled={disabled || reading}>
          {canPickFolders ? 'Choose a folder' : 'Choose files'}
        </button>
        {canPickFolders ? (
          <button
            type="button"
            className="link-button small"
            onClick={() => filesInput.current?.click()}
            disabled={disabled || reading}
          >
            Can’t pick a folder? Choose files instead
          </button>
        ) : (
          <p className="dropzone__hint">
            This browser can’t select folders, so choose the project’s files instead. You can select many at once.
          </p>
        )}
      </DropZone>
    </div>
  );
}
