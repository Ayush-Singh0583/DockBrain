/**
 * Demo-mode implementation of DockBrainService. It returns bundled fixtures about the
 * sample document and the DockBrain project, never results about the user's input.
 *
 * Privacy: it records only the selected file's or folder's name. It never reads file
 * contents, uploads anything, logs, or writes to browser storage.
 */
import type { DockBrainService } from './DockBrainService';
import {
  ServiceError,
  type Answer,
  type CardAnswer,
  type CardSet,
  type Capabilities,
  type CodebaseOverview,
  type Notes,
  type ProcessOptions,
  type Quiz,
  type RequestOptions,
  type SourceInput,
  type SourceSession,
} from './types';
import { SAMPLE_SECTION_COUNT, sampleAnswerFor, sampleCardAnswer, sampleCards, sampleNotes, sampleQuiz } from '../fixtures/sampleDocument';
import { sampleCodebaseOverview } from '../fixtures/sampleCodebase';
import { DEFAULT_MAX_DOCUMENT_BYTES, DOCUMENT_EXTENSIONS } from '../lib/fileValidation';
import { makeId } from '../lib/format';

export type MockOperation = 'open' | 'notes' | 'ask' | 'quiz' | 'cards' | 'codebase';

export interface MockServiceOptions {
  /** Base delay for each call, so loading states are visible. 0 in tests. */
  latencyMs?: number;
  /** Fail the next N calls of an operation, to demonstrate error states. */
  failures?: Partial<Record<MockOperation, number>>;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new ServiceError('aborted', 'The request was cancelled.'));
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(new ServiceError('aborted', 'The request was cancelled.'));
      },
      { once: true },
    );
  });
}

const DEMO_DOCUMENT_NOTICE =
  'Demo mode: your file stays on this device and was not read. Results come from DockBrain’s sample document.';
const DEMO_CODEBASE_NOTICE =
  'Demo mode: your folder stays on this device and was not read. The overview describes the DockBrain project.';

export class MockDockBrainService implements DockBrainService {
  readonly mode = 'demo' as const;
  private readonly latency: number;
  private readonly failures: Partial<Record<MockOperation, number>>;
  private readonly sessions = new Map<string, SourceInput['kind']>();

  constructor(options: MockServiceOptions = {}) {
    this.latency = options.latencyMs ?? 700;
    this.failures = { ...options.failures };
  }

  private async step(op: MockOperation, factor: number, signal?: AbortSignal): Promise<void> {
    await sleep(this.latency * factor, signal);
    const remaining = this.failures[op] ?? 0;
    if (remaining > 0) {
      this.failures[op] = remaining - 1;
      throw new ServiceError('network', 'DockBrain couldn’t be reached (simulated in demo mode).');
    }
  }

  private requireSession(sessionId: string, kind: SourceInput['kind']): void {
    if (this.sessions.get(sessionId) !== kind) {
      throw new ServiceError('not_found', 'This session has ended. Choose your file again to continue.', false);
    }
  }

  async getCapabilities(): Promise<Capabilities> {
    return {
      mode: 'demo',
      notes: 'demo',
      ask: 'demo',
      quiz: 'demo',
      cards: 'demo',
      codebase: 'demo',
      maxDocumentBytes: DEFAULT_MAX_DOCUMENT_BYTES,
      documentExtensions: DOCUMENT_EXTENSIONS,
      answerEngine: 'Sample answers (no AI service is contacted)',
    };
  }

  async openSource(input: SourceInput, options: ProcessOptions = {}): Promise<SourceSession> {
    const { onProgress, signal } = options;
    onProgress?.({
      stage: 'reading',
      message: 'Nothing is uploaded or read.',
    });
    await this.step('open', 1.2, signal);
    const id = makeId('demo');
    this.sessions.set(id, input.kind);
    onProgress?.({ stage: 'ready', fraction: 1, message: 'Demo workspace ready.' });
    return input.kind === 'document'
      ? { id, kind: 'document', displayName: input.file.name, demo: true, sectionCount: SAMPLE_SECTION_COUNT, notice: DEMO_DOCUMENT_NOTICE }
      : { id, kind: 'codebase', displayName: input.name, demo: true, notice: DEMO_CODEBASE_NOTICE };
  }

  async getNotes(sessionId: string, options: RequestOptions = {}): Promise<Notes> {
    await this.step('notes', 0.8, options.signal);
    this.requireSession(sessionId, 'document');
    return structuredClone(sampleNotes);
  }

  async ask(sessionId: string, question: string, options: RequestOptions = {}): Promise<Answer> {
    await this.step('ask', 1.4, options.signal);
    this.requireSession(sessionId, 'document');
    return sampleAnswerFor(question, makeId('answer'));
  }

  async getQuiz(sessionId: string, options: RequestOptions & { count?: number } = {}): Promise<Quiz> {
    await this.step('quiz', 1, options.signal);
    this.requireSession(sessionId, 'document');
    const quiz = structuredClone(sampleQuiz);
    if (options.count) quiz.questions = quiz.questions.slice(0, options.count);
    return quiz;
  }

  async getCards(sessionId: string, options: RequestOptions & { count?: number } = {}): Promise<CardSet> {
    await this.step('cards', 1, options.signal);
    this.requireSession(sessionId, 'document');
    const cards = structuredClone(sampleCards);
    if (options.count) cards.cards = cards.cards.slice(0, options.count);
    return cards;
  }

  async revealCard(sessionId: string, setId: string, cardId: string, options: RequestOptions = {}): Promise<CardAnswer> {
    await this.step('cards', 0.3, options.signal);
    this.requireSession(sessionId, 'document');
    const answer = setId === sampleCards.id ? sampleCardAnswer(cardId) : undefined;
    if (!answer) throw new ServiceError('not_found', 'That card isn’t in this set. Make a new set.', false);
    return answer;
  }

  async getCodebaseOverview(sessionId: string, options: RequestOptions = {}): Promise<CodebaseOverview> {
    await this.step('codebase', 1, options.signal);
    this.requireSession(sessionId, 'codebase');
    return structuredClone(sampleCodebaseOverview);
  }

  async closeSession(sessionId: string): Promise<void> {
    this.sessions.delete(sessionId);
  }
}
