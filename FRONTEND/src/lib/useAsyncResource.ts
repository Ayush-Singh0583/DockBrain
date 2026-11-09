import { useCallback, useEffect, useState } from 'react';
import { ServiceError, type ServiceErrorCode } from '../services/types';

export type Resource<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: T }
  | { status: 'error'; message: string; code?: ServiceErrorCode };

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ServiceError ? error.message : fallback;
}

/**
 * Loads data once `enabled` is true, cancels on unmount, and exposes `reload` for
 * retry buttons. `load` should be stable (wrap it in useCallback).
 */
export function useAsyncResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
  fallbackError = 'Something went wrong. Try again.',
): Resource<T> & { reload: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [resource, setResource] = useState<Resource<T>>({ status: 'idle' });

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setResource({ status: 'loading' });
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setResource({ status: 'success', data });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const code = error instanceof ServiceError ? error.code : undefined;
        setResource({ status: 'error', message: errorMessage(error, fallbackError), code });
      },
    );
    return () => controller.abort();
  }, [load, enabled, attempt, fallbackError]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...resource, reload };
}
