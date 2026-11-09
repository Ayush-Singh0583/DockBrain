import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/plus-jakarta-sans';
import './styles/tokens.css';
import './styles/base.css';
import './styles/ui.css';
import { App } from './app/App';
import { createService } from './services';
import { ServiceProvider } from './services/ServiceContext';

const service = createService();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ServiceProvider service={service}>
      <App />
    </ServiceProvider>
  </StrictMode>,
);
