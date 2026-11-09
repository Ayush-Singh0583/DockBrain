import { createContext, useContext, type ReactNode } from 'react';
import type { DockBrainService } from './DockBrainService';

const ServiceContext = createContext<DockBrainService | null>(null);

export function ServiceProvider({ service, children }: { service: DockBrainService; children: ReactNode }) {
  return <ServiceContext.Provider value={service}>{children}</ServiceContext.Provider>;
}

export function useService(): DockBrainService {
  const service = useContext(ServiceContext);
  if (!service) throw new Error('useService must be used inside <ServiceProvider>.');
  return service;
}
