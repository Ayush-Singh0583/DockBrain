import { useRef } from 'react';
import { FileText, RefreshCw, Trash2, Upload } from 'lucide-react';
import { DropZone } from './DropZone';
import { DOCUMENT_ACCEPT, FOLDER_IN_DOCUMENT_FLOW, validateDocumentList, type DocumentRules } from '../../lib/fileValidation';
import { extensionOf, formatBytes } from '../../lib/format';

export type PickerMessage = { tone: 'error' | 'warning'; text: string } | null;

const TYPE_LABELS: Record<string, string> = {
  '.pdf': 'PDF',
  '.docx': 'Word document',
  '.txt': 'Text file',
  '.md': 'Markdown',
  '.markdown': 'Markdown',
};

export function DocumentPicker({
  file,
  rules,
  disabled,
  onSelect,
  onRemove,
  onMessage,
}: {
  file: File | null;
  rules: DocumentRules;
  disabled: boolean;
  onSelect: (file: File) => void;
  onRemove: () => void;
  onMessage: (message: PickerMessage) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  const accept = (files: File[]) => {
    const result = validateDocumentList(files, rules);
    if (!result.ok) {
      onMessage({ tone: 'error', text: result.error });
      return;
    }
    onSelect(result.file);
    onMessage(result.warning ? { tone: 'warning', text: result.warning } : null);
  };

  const handleDrop = (dataTransfer: DataTransfer) => {
    if (disabled) return;
    const items = Array.from(dataTransfer.items ?? []);
    const droppedFolder = items.some((item) => item.webkitGetAsEntry?.()?.isDirectory);
    if (droppedFolder) {
      onMessage({ tone: 'error', text: FOLDER_IN_DOCUMENT_FLOW });
      return;
    }
    accept(Array.from(dataTransfer.files));
  };

  const openPicker = () => inputRef.current?.click();

  return (
    <div className="picker">
      <input
        ref={inputRef}
        type="file"
        accept={DOCUMENT_ACCEPT}
        className="visually-hidden"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="document-input"
        onChange={(event) => {
          accept(Array.from(event.target.files ?? []));
          event.target.value = ''; // so choosing the same file again still fires
        }}
      />

      {file ? (
        <div className="selected">
          <span className="selected__icon" aria-hidden="true">
            <FileText />
          </span>
          <div className="selected__text">
            <p className="selected__name" title={file.name}>
              {file.name}
            </p>
            <p className="selected__meta">
              {TYPE_LABELS[extensionOf(file.name)] ?? 'Document'} · {formatBytes(file.size)} · selected on this device
            </p>
          </div>
          <div className="selected__actions">
            <button type="button" className="btn btn--secondary btn--sm" onClick={openPicker} disabled={disabled}>
              <RefreshCw aria-hidden="true" />
              Replace
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={onRemove}
              disabled={disabled}
              aria-label={`Remove ${file.name}`}
            >
              <Trash2 aria-hidden="true" />
              Remove
            </button>
          </div>
        </div>
      ) : (
        <DropZone onDrop={handleDrop} label="Drop a document here">
          <span className="dropzone__icon" aria-hidden="true">
            <Upload />
          </span>
          <p className="dropzone__title">Drag a document here</p>
          <p className="dropzone__hint">PDF, Word (.docx), text or Markdown · up to {formatBytes(rules.maxBytes ?? 0)}</p>
          <button type="button" className="btn btn--primary" onClick={openPicker} disabled={disabled}>
            Choose a file
          </button>
        </DropZone>
      )}
    </div>
  );
}
