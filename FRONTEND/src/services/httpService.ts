/**
 * DRAFT adapter for the *proposed* HTTP API in API_CONTRACT.md. No DockBrain server
 * implements this API yet; the Python backend is a CLI. It is covered only by unit tests
 * with a mocked `fetch`, and is used only when VITE_DOCKBRAIN_API_URL is set.
 *
 * Provider API keys stay on the server. This adapter never sends or stores them.
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
  type ProcessingStage,
  type Quiz,
  type RequestOptions,
  type ServiceErrorCode,
  type SourceInput,
  type SourceSession,
} from './types';

/** Session resource returned by POST /sessions and GET /sessions/{id}. */
interface SessionResource {
  id: string;
  kind: SourceInput['kind'];
  displayName: string;
  status: 'processing' | 'ready' | 'failed';
  stage?: ProcessingStage;
  progress?: number;
  message?: string;
  sectionCount?: number;
  notice?: string;
  error?: { code?: ServiceErrorCode; message?: string };
}

const STATUS_CODES: Record<number, ServiceErrorCode> = {
  404: 'not_found',
  413: 'too_large',
  415: 'unsupported',
  422: 'unreadable',
  429: 'rate_limited',
  503: 'unavailable',
};

const FALLBACK_MESSAGES: Record<ServiceErrorCode, string> = {
  network: 'DockBrain couldn’t be reached. Check that the server is running, then try again.',
  too_large: 'That file is larger than the server accepts. Choose a smaller file.',
  unsupported: 'The server can’t read this type of file. Choose a PDF, DOCX, TXT or Markdown file.',
  unreadable: 'The server couldn’t read any text from this file. It may be scanned or password-protected.',
  rate_limited: 'The answer service is busy or has reached its limit. Wait a moment, then try again.',
  insufficient_content: 'This document doesn’t have enough plain statements to work from. Try a longer document.',
  not_found: 'This session has ended. Choose your file again to continue.',
  unavailable: 'DockBrain is temporarily unavailable. Try again in a moment.',
  aborted: 'The request was cancelled.',
  unknown: 'Something went wrong on the server. Try again.',
};

export interface HttpServiceOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  pollIntervalMs?: number;
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new ServiceError('aborted', FALLBACK_MESSAGES.aborted));
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(new ServiceError('aborted', FALLBACK_MESSAGES.aborted));
      },
      { once: true },
    );
  });
}

export class HttpDockBrainService implements DockBrainService {
  readonly mode = 'live' as const;
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly pollIntervalMs: number;

  constructor({ baseUrl, fetchImpl, pollIntervalMs = 800 }: HttpServiceOptions) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.fetchImpl = fetchImpl ?? ((...args) => globalThis.fetch(...args));
    this.pollIntervalMs = pollIntervalMs;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        headers: { Accept: 'application/json', ...init.headers },
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new ServiceError('aborted', FALLBACK_MESSAGES.aborted);
      }
      if (error instanceof ServiceError) throw error;
      throw new ServiceError('network', FALLBACK_MESSAGES.network);
    }

    if (response.status === 204) return undefined as T;
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const err = (body as { error?: { code?: ServiceErrorCode; message?: string; retryable?: boolean } } | null)?.error;
      const code = err?.code ?? STATUS_CODES[response.status] ?? (response.status >= 500 ? 'unavailable' : 'unknown');
      throw new ServiceError(code, err?.message ?? FALLBACK_MESSAGES[code], err?.retryable);
    }
    if (body === null) throw new ServiceError('unknown', 'The server sent a response DockBrain couldn’t read.');
    return body as T;
  }

  private json(method: string, payload: unknown, signal?: AbortSignal): RequestInit {
    return { method, body: JSON.stringify(payload), headers: { 'Content-Type': 'application/json' }, signal };
  }

  async getCapabilities(options: RequestOptions = {}): Promise<Capabilities> {
    return this.request<Capabilities>('/capabilities', { signal: options.signal });
  }

  async openSource(input: SourceInput, options: ProcessOptions = {}): Promise<SourceSession> {
    const { signal, onProgress } = options;
    const form = new FormData();
    form.append('kind', input.kind);
    if (input.kind === 'document') {
      form.append('file', input.file, input.file.name);
    } else {
      form.append('name', input.name);
      form.append('manifest', JSON.stringify(input.files.map((f) => ({ path: f.path, size: f.size }))));
      for (const f of input.files) form.append('files', f.file, f.path);
    }

    onProgress?.({ stage: 'uploading', message: 'Uploading to your DockBrain server…' });
    let session = await this.request<SessionResource>('/sessions', { method: 'POST', body: form, signal });

    // From here the server holds a session. If it isn't returned to the app (cancelled,
    // failed, or a poll error), the app can't close it, so close it here. The DELETE is
    // best effort and deliberately not tied to `signal`, which may already be aborted.
    try {
      while (session.status === 'processing') {
        onProgress?.({
          stage: session.stage ?? 'indexing',
          fraction: session.progress,
          message: session.message ?? 'Reading and indexing…',
        });
        await wait(this.pollIntervalMs, signal);
        session = await this.request<SessionResource>(this.sessionPath(session.id, ''), { signal });
      }
      if (session.status === 'failed') {
        const code = session.error?.code ?? 'unreadable';
        throw new ServiceError(code, session.error?.message ?? FALLBACK_MESSAGES[code]);
      }
      if (signal?.aborted) throw new ServiceError('aborted', FALLBACK_MESSAGES.aborted);
    } catch (error) {
      void this.closeSession(session.id);
      throw signal?.aborted ? new ServiceError('aborted', FALLBACK_MESSAGES.aborted) : error;
    }
    onProgress?.({ stage: 'ready', fraction: 1, message: 'Ready.' });
    return {
      id: session.id,
      kind: session.kind,
      displayName: session.displayName,
      demo: false,
      sectionCount: session.sectionCount,
      notice: session.notice,
    };
  }

  private sessionPath(sessionId: string, rest: string): string {
    return `/sessions/${encodeURIComponent(sessionId)}${rest}`;
  }

  async getNotes(sessionId: string, options: RequestOptions = {}): Promise<Notes> {
    const notes = await this.request<Notes>(this.sessionPath(sessionId, '/notes'), { signal: options.signal });
    return { ...notes, demo: notes.demo ?? false, suggestedQuestions: notes.suggestedQuestions ?? [] };
  }

  async ask(sessionId: string, question: string, options: RequestOptions = {}): Promise<Answer> {
    const answer = await this.request<Answer>(
      this.sessionPath(sessionId, '/questions'),
      this.json('POST', { question }, options.signal),
    );
    return { ...answer, question: answer.question ?? question, citations: answer.citations ?? [], demo: answer.demo ?? false };
  }

  async getQuiz(sessionId: string, options: RequestOptions & { count?: number } = {}): Promise<Quiz> {
    const quiz = await this.request<Quiz>(
      this.sessionPath(sessionId, '/quizzes'),
      this.json('POST', { count: options.count ?? 5 }, options.signal),
    );
    return { ...quiz, demo: quiz.demo ?? false };
  }

  async getCards(sessionId: string, options: RequestOptions & { count?: number } = {}): Promise<CardSet> {
    const cards = await this.request<CardSet>(
      this.sessionPath(sessionId, '/cards'),
      this.json('POST', { count: options.count ?? 10 }, options.signal),
    );
    return { ...cards, notice: cards.notice ?? null, demo: cards.demo ?? false };
  }

  async revealCard(sessionId: string, setId: string, cardId: string, options: RequestOptions = {}): Promise<CardAnswer> {
    const path = `/cards/${encodeURIComponent(setId)}/answers/${encodeURIComponent(cardId)}`;
    return this.request<CardAnswer>(this.sessionPath(sessionId, path), { signal: options.signal });
  }

  async getCodebaseOverview(sessionId: string, options: RequestOptions = {}): Promise<CodebaseOverview> {
    const overview = await this.request<CodebaseOverview>(this.sessionPath(sessionId, '/overview'), {
      signal: options.signal,
    });
    return { ...overview, demo: overview.demo ?? false };
  }

  async closeSession(sessionId: string): Promise<void> {
    try {
      await this.request<void>(this.sessionPath(sessionId, ''), { method: 'DELETE' });
    } catch {
      // Closing is best effort; the server should also expire idle sessions.
    }
  }
}
