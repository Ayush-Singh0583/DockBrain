/**
 * Demo fixture for the codebase flow: a hand-written overview of the DockBrain project
 * itself (as of 2026-11-07), not an analysis of the folder the user selected. The UI
 * labels it as demo content.
 */
import type { CodebaseOverview } from '../services/types';

export const sampleCodebaseOverview: CodebaseOverview = {
  projectName: 'DockBrain',
  demo: true,
  answers: [
    {
      id: 'about',
      question: 'What is this codebase about?',
      summary:
        'DockBrain is a command-line assistant that answers questions about a single document — plain text, Markdown, Word or PDF — and shows which passages each answer came from.',
      details: [
        'A document is loaded, split into sentence-aligned sections of about 120 words, and indexed in memory.',
        'Each question retrieves the four best-matching sections.',
        'Answers come from local sentence extraction, or from Gemini or Claude when an API key is configured.',
      ],
      evidence: [
        { index: 1, path: 'main.py', excerpt: 'CLI arguments, provider selection and the interactive question loop.' },
        { index: 2, path: 'rag/__init__.py', excerpt: 'RAG: load → chunk → index once; retrieve and generate per question.' },
      ],
    },
    {
      id: 'why',
      question: 'Why was it created?',
      summary:
        'Finding one fact in a long report is slow, and general chatbots can answer confidently without showing where the answer came from.',
      details: [
        'Answers should be grounded in the user’s own document and cite the passages they rely on.',
        'It should still work with no API key and nothing sent anywhere (offline mode).',
      ],
      evidence: [{ index: 1, path: 'main.py', excerpt: 'Without a key, or with --offline, nothing is sent anywhere.' }],
    },
    {
      id: 'problem',
      question: 'What problem does it solve?',
      summary:
        'Getting trustworthy answers from one document — and being honest when the document doesn’t seem to contain them.',
      details: [
        'PDF text arrives with running headers, page numbers and broken words that can bury or delete facts.',
        'Questions often use different words from the document, so simple search misses relevant passages.',
        'A search miss is easy to mistake for proof that the document lacks the answer.',
      ],
      evidence: [
        { index: 1, path: 'rag/loader.py', excerpt: 'PDF extraction and page-furniture cleanup.' },
        { index: 2, path: 'rag/retriever.py', excerpt: 'BM25 search with word forms and heading boosts.' },
      ],
    },
    {
      id: 'how',
      question: 'How does it solve that problem?',
      summary:
        'It retrieves evidence before answering, and labels every answer with where it came from.',
      details: [
        'Lexical BM25 retrieval matches other forms of a word, so “produces” can find “production”.',
        'Documents of six sections or fewer are sent whole; larger ones say how many sections were searched.',
        'Online replies must cite real excerpts or carry an outside-knowledge label, enforced in code.',
        'When the model can’t find an answer, it can suggest other words for one more search.',
      ],
      evidence: [
        { index: 1, path: 'rag/retriever.py', excerpt: 'BM25Retriever: word forms at half weight, search excluding sections already sent.' },
        { index: 2, path: 'rag/generator.py', excerpt: 'with_provenance and _OnlineGenerator: origin labels, coverage wording, second search.' },
      ],
    },
  ],
  distinctive: [
    'Answer-origin labels are enforced in code, not left to the model’s wording.',
    'It states how much of the document it searched before saying something isn’t there.',
    'It runs fully offline with extractive answers when no key is set.',
    'PDF cleanup removes page furniture only on positive evidence, to avoid deleting facts.',
  ],
};
