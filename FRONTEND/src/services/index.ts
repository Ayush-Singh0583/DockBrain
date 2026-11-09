/**
 * Chooses the service implementation from configuration:
 * - VITE_DOCKBRAIN_API_URL set   → HttpDockBrainService (draft adapter, proposed API)
 * - otherwise                    → MockDockBrainService (demo fixtures)
 *
 * Demo-only URL switch for reviewing error states: ?simulate=ask-error (also open-,
 * notes-, quiz-, cards-, codebase-error) makes the first such call fail once.
 */
import type { DockBrainService } from './DockBrainService';
import { HttpDockBrainService } from './httpService';
import { MockDockBrainService, type MockOperation } from './mockService';

const OPERATIONS: MockOperation[] = ['open', 'notes', 'ask', 'quiz', 'cards', 'codebase'];

export function simulatedFailures(search: string): Partial<Record<MockOperation, number>> {
  const failures: Partial<Record<MockOperation, number>> = {};
  const values = new URLSearchParams(search).getAll('simulate').flatMap((v) => v.split(','));
  for (const value of values) {
    const op = value.replace(/-error$/, '') as MockOperation;
    if (OPERATIONS.includes(op)) failures[op] = 1;
  }
  return failures;
}

export function createService(
  env: { VITE_DOCKBRAIN_API_URL?: string } = import.meta.env,
  search: string = typeof window === 'undefined' ? '' : window.location.search,
): DockBrainService {
  const baseUrl = env.VITE_DOCKBRAIN_API_URL?.trim();
  if (baseUrl) return new HttpDockBrainService({ baseUrl });
  return new MockDockBrainService({ failures: simulatedFailures(search) });
}

export type { DockBrainService } from './DockBrainService';
export * from './types';
