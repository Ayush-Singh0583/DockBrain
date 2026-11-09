import { useEffect, useReducer, useRef, useState } from 'react';
import { useService } from '../services/ServiceContext';
import type { Capabilities } from '../services/types';
import { appReducer, initialState } from './state';
import { TopBar } from './TopBar';
import { WelcomeScreen } from '../screens/WelcomeScreen';
import { SelectScreen } from '../screens/SelectScreen';
import { WorkspaceScreen } from '../screens/workspace/WorkspaceScreen';
import { CodebaseScreen } from '../screens/CodebaseScreen';
import { NavigationContext } from './navigation';

export function App() {
  const service = useService();
  const [state, dispatch] = useReducer(appReducer, initialState);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [capabilitiesError, setCapabilitiesError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    service
      .getCapabilities({ signal: controller.signal })
      .then(setCapabilities)
      .catch(() => {
        if (!controller.signal.aborted) setCapabilitiesError(true);
      });
    return () => controller.abort();
  }, [service]);

  // End a session on the service side whenever the app lets go of it.
  const sessionId = state.session?.id;
  useEffect(() => {
    if (!sessionId) return;
    return () => {
      void service.closeSession(sessionId);
    };
  }, [service, sessionId]);

  // After the first navigation, each new screen focuses its heading (useScreenHeading).
  // Recorded during render because the new screen's effects run before this component's.
  const navigated = useRef(false);
  const firstScreen = useRef(state.screen);
  if (state.screen !== firstScreen.current) navigated.current = true;
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [state.screen]);

  const screenProps = { state, dispatch, capabilities };

  return (
    <NavigationContext.Provider value={navigated}>
      <div className="app" data-screen={state.screen}>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <TopBar mode={service.mode} capabilities={capabilities} unreachable={capabilitiesError} />
        <main id="main" className="app__main">
          <div className="screen" key={state.screen + (state.session?.id ?? '')}>
            {state.screen === 'welcome' && <WelcomeScreen {...screenProps} />}
            {state.screen === 'select' && <SelectScreen {...screenProps} />}
            {state.screen === 'workspace' && state.session && state.document && (
              <WorkspaceScreen {...screenProps} session={state.session} document={state.document} />
            )}
            {state.screen === 'codebase' && state.session && state.codebase && (
              <CodebaseScreen {...screenProps} session={state.session} selection={state.codebase} />
            )}
          </div>
        </main>
      </div>
    </NavigationContext.Provider>
  );
}
