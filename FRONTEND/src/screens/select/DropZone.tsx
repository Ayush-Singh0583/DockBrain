import { useRef, useState, type DragEvent, type ReactNode } from 'react';

/**
 * A drop target. It is not focusable itself: keyboard users use the buttons inside it,
 * which open the same file pickers.
 */
export function DropZone({
  onDrop,
  children,
  label,
}: {
  onDrop: (dataTransfer: DataTransfer) => void;
  children: ReactNode;
  label: string;
}) {
  const [over, setOver] = useState(false);
  const depth = useRef(0); // dragenter/leave fire for every child element

  const hasFiles = (event: DragEvent) => Array.from(event.dataTransfer.types).includes('Files');

  return (
    <div
      className="dropzone"
      data-over={over}
      role="group"
      aria-label={label}
      onDragEnter={(event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        depth.current += 1;
        setOver(true);
      }}
      onDragOver={(event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
      }}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setOver(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        depth.current = 0;
        setOver(false);
        onDrop(event.dataTransfer);
      }}
    >
      {children}
    </div>
  );
}
