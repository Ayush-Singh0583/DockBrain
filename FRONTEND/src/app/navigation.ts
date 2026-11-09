import { createContext, useContext, useEffect, useRef, type Dispatch, type RefObject } from 'react';
import type { Capabilities } from '../services/types';
import type { AppAction, AppState } from './state';

export interface ScreenProps {
  state: AppState;
  dispatch: Dispatch<AppAction>;
  capabilities: Capabilities | null;
}

/** True once the user has moved between screens (not on first load). */
export const NavigationContext = createContext<RefObject<boolean> | null>(null);

/**
 * Focus a screen's main heading when it opens after navigation, so keyboard and
 * screen-reader users land at the start of the new content.
 */
export function useScreenHeading<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const navigated = useContext(NavigationContext);
  useEffect(() => {
    if (navigated?.current) ref.current?.focus({ preventScroll: true });
  }, [navigated]);
  return ref;
}
