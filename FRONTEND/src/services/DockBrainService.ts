import type {
  Answer,
  CardAnswer,
  CardSet,
  Capabilities,
  CodebaseOverview,
  Notes,
  ProcessOptions,
  Quiz,
  RequestOptions,
  SourceInput,
  SourceSession,
} from './types';

/**
 * The one interface screens talk to. `MockDockBrainService` implements it with fixtures
 * today; `HttpDockBrainService` implements it against the proposed HTTP API in
 * API_CONTRACT.md. Choosing between them is configuration (see ./index.ts).
 *
 * Every method rejects with `ServiceError`.
 */
export interface DockBrainService {
  readonly mode: 'demo' | 'live';

  getCapabilities(options?: RequestOptions): Promise<Capabilities>;

  /** Upload (live) or register (demo) the selected document or folder, then index it. */
  openSource(input: SourceInput, options?: ProcessOptions): Promise<SourceSession>;

  getNotes(sessionId: string, options?: RequestOptions): Promise<Notes>;

  ask(sessionId: string, question: string, options?: RequestOptions): Promise<Answer>;

  getQuiz(sessionId: string, options?: RequestOptions & { count?: number }): Promise<Quiz>;

  /** A new set of memory cards for a document session: fronts only. */
  getCards(sessionId: string, options?: RequestOptions & { count?: number }): Promise<CardSet>;

  /** One card's answer, source sentence and passage, when the learner reveals it. */
  revealCard(sessionId: string, setId: string, cardId: string, options?: RequestOptions): Promise<CardAnswer>;

  getCodebaseOverview(sessionId: string, options?: RequestOptions): Promise<CodebaseOverview>;

  /** Forget the session and anything uploaded for it. Never rejects. */
  closeSession(sessionId: string): Promise<void>;
}
