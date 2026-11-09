import type { CSSProperties, ReactNode } from 'react';
import { AlertTriangle, CircleHelp, FileCheck2, FlaskConical, Globe2, Info, RotateCw, Split } from 'lucide-react';
import type { AnswerOrigin } from '../services/types';

export function SpeechBubble({
  tail = 'none',
  tailOffset,
  className,
  children,
  live = false,
  id,
}: {
  tail?: 'top' | 'left' | 'bottom' | 'none';
  /** CSS length for where the tail sits along its edge, e.g. "40px" or "30%". */
  tailOffset?: string;
  className?: string;
  children: ReactNode;
  /** Announce changes politely, for status messages that change with activity. */
  live?: boolean;
  id?: string;
}) {
  const style = tailOffset ? ({ '--tail-offset': tailOffset } as CSSProperties) : undefined;
  return (
    <div
      id={id}
      className={['bubble', `bubble--tail-${tail}`, className].filter(Boolean).join(' ')}
      style={style}
      role={live ? 'status' : undefined}
    >
      {children}
    </div>
  );
}

const NOTICE_ICONS = { demo: FlaskConical, info: Info, warning: AlertTriangle, error: AlertTriangle, success: FileCheck2 };

export function Notice({
  tone,
  title,
  children,
  action,
  role,
}: {
  tone: keyof typeof NOTICE_ICONS;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  role?: 'alert' | 'status';
}) {
  const Icon = NOTICE_ICONS[tone];
  return (
    <div className={`notice notice--${tone}`} role={role}>
      <Icon aria-hidden="true" />
      <div className="notice__body">
        {title && <p className="notice__title">{title}</p>}
        {children && <div>{children}</div>}
      </div>
      {action}
    </div>
  );
}

export const ORIGIN_LABELS: Record<AnswerOrigin, string> = {
  document: 'From the document',
  mixed: 'Partly from the document',
  general: 'General knowledge',
  insufficient: 'Not enough evidence',
};

const ORIGIN_ICONS = { document: FileCheck2, mixed: Split, general: Globe2, insufficient: CircleHelp };

export function OriginBadge({ origin }: { origin: AnswerOrigin }) {
  const Icon = ORIGIN_ICONS[origin];
  return (
    <span className={`origin origin--${origin}`}>
      <Icon aria-hidden="true" />
      {ORIGIN_LABELS[origin]}
    </span>
  );
}

export function Skeleton({ lines = 4, title = true, label }: { lines?: number; title?: boolean; label: string }) {
  return (
    <div className="skeleton" role="status" aria-label={label}>
      {title && <div className="skeleton__line skeleton__line--title" />}
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton__line" style={{ width: `${92 - ((i * 17) % 35)}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ title, message, onRetry, retryLabel = 'Try again' }: {
  title: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div className="state state--error" role="alert">
      <p className="state__title">{title}</p>
      <p className="muted">{message}</p>
      {onRetry && (
        <button type="button" className="btn btn--secondary btn--sm" onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          {retryLabel}
        </button>
      )}
    </div>
  );
}

/** Small DockBrain mark: the robot's face, used in the top bar. */
export function BrandMark() {
  return (
    <svg className="brand__mark" viewBox="0 0 34 34" aria-hidden="true">
      <line x1="17" y1="6.2" x2="17" y2="3.6" stroke="#9fb0d6" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="17" cy="3" r="2" fill="#7fe6ff" />
      <rect x="2.5" y="6.2" width="29" height="24" rx="10.5" fill="#f7f9ff" stroke="#b9c4de" strokeWidth="0.8" />
      <rect x="6.4" y="10" width="21.2" height="15.8" rx="7" fill="#0f1b42" />
      <ellipse cx="12.6" cy="16.6" rx="2" ry="2.5" fill="#7fe6ff" />
      <ellipse cx="21.4" cy="16.6" rx="2" ry="2.5" fill="#7fe6ff" />
      <path d="M14.2 21.2q2.8 2 5.6 0" fill="none" stroke="#7fe6ff" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
