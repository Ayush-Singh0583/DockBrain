import { useEffect } from 'react';
import type { Say } from '../screens/workspace/WorkspaceScreen';

export const STILL_WORKING_AFTER_MS = 8000;

/** A model can take a minute or more; say so, rather than seeming to have stopped. */
export function useStillWorking(loading: boolean, say: Say): void {
  useEffect(() => {
    if (!loading) return;
    const timer = setTimeout(() => say('think', 'Still working on it. This can take a minute or two.'), STILL_WORKING_AFTER_MS);
    return () => clearTimeout(timer);
  }, [loading, say]);
}
