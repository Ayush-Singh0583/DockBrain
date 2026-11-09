/**
 * Domain types shared by the UI and every DockBrain service adapter.
 *
 * They mirror what the Python backend already produces where possible (answers with
 * numbered excerpt citations, "wasn't in the information I was given" labels, how many
 * sections were searched) and propose the rest. See API_CONTRACT.md.
 */

export type Activity = 'learn' | 'quiz' | 'cards' | 'codebase';

/** Whether a feature is backed by real analysis, sample fixtures, or not offered. */
export type FeatureStatus = 'available' | 'demo' | 'unavailable';

export interface Capabilities {
  /** 'demo' means every result comes from bundled fixtures, not from the user's input. */
  mode: 'demo' | 'live';
  notes: FeatureStatus;
  ask: FeatureStatus;
  quiz: FeatureStatus;
  /** Memory cards. A server that predates them omits this, and they aren't offered. */
  cards?: FeatureStatus;
  codebase: FeatureStatus;
  /** Largest document the backend accepts, in bytes. */
  maxDocumentBytes: number;
  /** Lower-case extensions including the dot, e.g. ".pdf". */
  documentExtensions: string[];
  /** Short description of where answers come from, e.g. "Offline extractive answers". */
  answerEngine: string;
}

export type Feature = 'notes' | 'ask' | 'quiz' | 'cards' | 'codebase';

/**
 * Whether to offer a feature at all. Until capabilities arrive (or if they can't be
 * fetched) everything is offered, and a request's own error explains any failure. A
 * feature the server's capabilities don't mention (one added after that server) isn't.
 */
export function offers(capabilities: Capabilities | null, feature: Feature): boolean {
  if (!capabilities) return true;
  const status = capabilities[feature];
  return status !== undefined && status !== 'unavailable';
}

/* ------------------------------------------------------------------ inputs */

/** One file inside a selected codebase folder. Contents are read only by a live adapter. */
export interface CodeFile {
  /** Path relative to the selected folder, using "/" separators. */
  path: string;
  size: number;
  file: File;
}

export type SourceInput =
  | { kind: 'document'; file: File }
  | { kind: 'codebase'; name: string; files: CodeFile[] };

export type ProcessingStage = 'uploading' | 'reading' | 'indexing' | 'ready';

export interface ProcessingProgress {
  stage: ProcessingStage;
  /** 0–1 when the adapter can measure it. */
  fraction?: number;
  message: string;
}

export interface SourceSession {
  id: string;
  kind: SourceInput['kind'];
  /** The user's file or folder name. */
  displayName: string;
  /** True when results come from fixtures and the user's input was not analysed. */
  demo: boolean;
  /** Number of indexed sections (the backend's chunks), when known. */
  sectionCount?: number;
  /** Shown near the document name, e.g. "Demo mode: your file was not uploaded". */
  notice?: string;
}

/* ---------------------------------------------------------------- evidence */

/**
 * A numbered excerpt an answer can cite as [n]. Location fields are optional and the UI
 * shows only those supplied: the current backend knows section headings, not pages.
 */
export interface Citation {
  index: number;
  excerpt: string;
  section?: string;
  page?: number;
  /** File path, for codebase evidence. */
  path?: string;
  lineStart?: number;
  lineEnd?: number;
  /** Retrieval score, for debugging views. */
  score?: number;
}

/**
 * - document: supported by cited excerpts.
 * - mixed: partly cited, partly general knowledge (labelled in the text).
 * - general: answered from general knowledge; the document didn't contain it (as far
 *   as the search could tell, see `coverage`).
 * - insufficient: no answer; the evidence found wasn't enough.
 */
export type AnswerOrigin = 'document' | 'mixed' | 'general' | 'insufficient';

export interface SearchCoverage {
  /** Sections actually given to the answer engine. */
  searched: number;
  /** Sections in the whole document. */
  total: number;
}

export interface Answer {
  id: string;
  question: string;
  /** Plain text; may contain [n] markers referring to `citations`. */
  text: string;
  origin: AnswerOrigin;
  citations: Citation[];
  coverage?: SearchCoverage;
  demo: boolean;
}

/* ------------------------------------------------------------------- notes */

export interface NotePoint {
  text: string;
  /** Indices into Notes.sources. */
  citations?: number[];
}

export interface NoteSection {
  id: string;
  heading: string;
  points: NotePoint[];
}

export interface Notes {
  title: string;
  summary: string;
  sections: NoteSection[];
  sources: Citation[];
  /** Questions the UI can offer as starting points in the Ask view. */
  suggestedQuestions: string[];
  /** Why these notes aren't the kind the server normally writes, if they aren't. */
  notice?: string | null;
  demo: boolean;
}

/* -------------------------------------------------------------------- quiz */

export interface QuizOption {
  id: string;
  text: string;
}

export interface QuizQuestion {
  id: string;
  prompt: string;
  options: QuizOption[];
  correctOptionId: string;
  explanation: string;
  citation?: Citation;
}

export interface Quiz {
  id: string;
  title: string;
  questions: QuizQuestion[];
  demo: boolean;
}

/* ------------------------------------------------------------ memory cards */

/** 'question' cards are written by a model; the others are built from the document's sentences. */
export type CardKind = 'definition' | 'cloze' | 'question';

/** The front of a memory card. Its answer is fetched only when the learner reveals it. */
export interface MemoryCard {
  id: string;
  kind: CardKind;
  prompt: string;
}

export interface CardSet {
  id: string;
  title: string;
  cards: MemoryCard[];
  /** Why there are fewer cards than asked for, if there are. */
  notice?: string | null;
  demo: boolean;
}

/** A revealed card: its answer, the sentence it comes from, and that sentence's passage. */
export interface CardAnswer {
  cardId: string;
  /** Words from `quote`, or on a 'question' card a short answer that `quote` supports. */
  answer: string;
  quote: string;
  citation: Citation;
}

/* ---------------------------------------------------------------- codebase */

export type OverviewQuestionId = 'about' | 'why' | 'problem' | 'how';

export interface OverviewAnswer {
  id: OverviewQuestionId;
  question: string;
  summary: string;
  details: string[];
  evidence: Citation[];
}

export interface CodebaseOverview {
  /** Name of the project the content describes (may differ from the selected folder in demo mode). */
  projectName: string;
  answers: OverviewAnswer[];
  distinctive: string[];
  demo: boolean;
}

/* ------------------------------------------------------------------ errors */

export type ServiceErrorCode =
  | 'network'
  | 'too_large'
  | 'unsupported'
  | 'unreadable'
  | 'rate_limited'
  | 'insufficient_content'
  | 'not_found'
  | 'unavailable'
  | 'aborted'
  | 'unknown';

/** Every adapter throws this, so screens can show one consistent message per code. */
export class ServiceError extends Error {
  readonly code: ServiceErrorCode;
  readonly retryable: boolean;

  constructor(code: ServiceErrorCode, message: string, retryable = code !== 'unsupported') {
    super(message);
    this.name = 'ServiceError';
    this.code = code;
    this.retryable = retryable;
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface ProcessOptions extends RequestOptions {
  onProgress?: (progress: ProcessingProgress) => void;
}
