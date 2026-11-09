# DockBrain HTTP API contract

> **Status (2026-11-08): partly implemented.** The server is the `server/` package at the
> repository root (Python standard library only), and it serves:
>
> - `GET /capabilities`;
> - document sessions (`POST /sessions`, `GET` and `DELETE /sessions/{id}`);
> - `POST /sessions/{id}/questions`;
> - `GET /sessions/{id}/notes`;
> - `GET /sessions/{id}/passages/{passageId}`;
> - the quiz endpoints in the Quiz section;
> - the memory card endpoints in the Memory cards section.
>
> It doesn't implement codebase sessions or the codebase overview, and reports them as
> `unavailable`. The frontend's adapter (`src/services/httpService.ts`) has been run
> against the real server, not only a mocked `fetch`.

## Connecting the frontend

1. Start the server from the repository root:
   `python -m server [--host 127.0.0.1] [--port 8000] [--offline]`. It picks the answer
   engine like the CLI: Ollama if `OLLAMA_MODEL` is set (a model on this computer, so
   nothing leaves it), then Gemini, then Claude, else offline extractive. Settings come
   from the terminal or the root `.env`. `--offline` uses no model and sends nothing
   anywhere. With Ollama, `ollama serve` must be running; the server warns at startup if
   it isn't, or if the model isn't installed.
2. Set `VITE_DOCKBRAIN_API_URL` in `FRONTEND/.env.local`, e.g.
   `VITE_DOCKBRAIN_API_URL=http://127.0.0.1:8000/api/v1`, and rebuild or restart.
3. The app switches from `MockDockBrainService` to `HttpDockBrainService` (see
   `src/services/index.ts`); the top bar then shows "Connected" instead of "Demo mode".

Server settings, from the environment:

- `DOCKBRAIN_CORS_ORIGINS`: comma-separated origins allowed to call from a browser. The
  default allows the Vite dev and preview servers on `localhost` and `127.0.0.1`, ports
  5173 and 4173.
- `DOCKBRAIN_SESSION_TTL`: seconds a session may go unused before it is deleted. The
  default is 1800.

If the server's responses differ from this contract, change the adapter, not the
screens. Screens only use the `DockBrainService` interface in
`src/services/DockBrainService.ts`.

## Principles

- **Provider keys stay on the server.** Gemini/Claude keys are read from the server's
  environment or `.env`, as `main.py` does today. The browser never sees them.
- **Every result says whether it is real.** Each notes, answer, quiz, card set and
  overview payload has `demo: boolean`. A live server sends `false`, or `true` only for genuinely
  canned content. The UI labels each result by its own flag: sample notes in a live
  session are marked as a sample, without claiming the uploaded document went unread.
- **Capabilities decide what is offered.** A feature reported as `unavailable` gets no
  activity card, tab or link, and its endpoint is never called. `demo` features are
  requested and labelled as samples. An ask-only server is therefore a valid first
  step: report `notes`, `quiz` and `codebase` as `unavailable`.
- **Uploads are temporary.** The uploaded file is deleted as soon as it has been read and
  indexed, or has failed to read. The index is deleted on `DELETE /sessions/{id}` and after
  the idle timeout. Logs record only the method, the route pattern (e.g.
  `POST /sessions/{session_id}/questions`), the status and the duration. They never record
  session ids, file names, document text, questions or answers.
- **Errors are structured** (see below), and their messages can be shown to people
  as they are.
- Same-origin hosting is simplest. Otherwise allow the frontend's origin with CORS.
  Credentials aren't required by this contract.

## Types

JSON shapes match the TypeScript types in `src/services/types.ts`, which are the source
of truth. Optional fields may be omitted. The UI shows page, section and line locations
only when they are present.

```ts
Citation       { index: number; excerpt: string; section?: string; page?: number;
                 path?: string; lineStart?: number; lineEnd?: number; score?: number;
                 passageId?: number }
AnswerOrigin   "document" | "mixed" | "general" | "insufficient"
Answer         { id: string; question: string; text: string; origin: AnswerOrigin;
                 citations: Citation[]; coverage?: { searched: number; total: number };
                 demo: boolean }
Notes          { title: string; summary: string;
                 sections: { id: string; heading: string;
                             points: { text: string; citations?: number[] }[] }[];
                 sources: Citation[]; suggestedQuestions: string[]; notice?: string | null;
                 demo: boolean }
Quiz           { id: string; title: string; demo: boolean;
                 questions: { id: string; prompt: string; options: { id: string; text: string }[];
                              correctOptionId: string; explanation: string; citation?: Citation }[] }
CodebaseOverview { projectName: string; demo: boolean; distinctive: string[];
                   answers: { id: "about" | "why" | "problem" | "how"; question: string;
                              summary: string; details: string[]; evidence: Citation[] }[] }
CardSet        { id: string; title: string; notice?: string | null; demo: boolean;
                 cards: { id: string; kind: "definition" | "cloze" | "question"; prompt: string }[] }
CardAnswer     { cardId: string; answer: string; quote: string; citation: Citation }
Capabilities   { mode: "live" | "demo"; notes, ask, quiz, codebase: "available" | "demo" | "unavailable";
                 cards?: "available" | "demo" | "unavailable";
                 maxDocumentBytes: number; documentExtensions: string[]; answerEngine: string }
```

`cards` is optional because servers from before memory cards don't send it. The frontend
treats any feature missing from `Capabilities` as `unavailable`.

`text` in an answer may contain `[n]` markers. Each must match a `Citation.index` in the
same answer; the UI leaves unmatched markers as plain text. Indices start at 1 per
answer, as the backend's `with_provenance` already enforces.

`passageId` identifies a document passage (the backend's chunk, numbered from 0 in
document order). The full passage can be fetched with
`GET /sessions/{id}/passages/{passageId}`.

What each `AnswerOrigin` means in practice:

| Origin | When | `citations` |
| --- | --- | --- |
| `document` | Cited excerpts support the answer. Offline answers quote document sentences without `[n]` markers. | The cited excerpts, or offline the quoted ones. |
| `mixed` | Partly cited; the rest is labelled "The rest wasn't in the information I was given, but…" | Only the cited excerpts. |
| `general` | Labelled general knowledge ("It wasn't in the information I was given, but…", or "I searched N of M sections…" when only part was read). | `[]` |
| `insufficient` | No answer: no passage matched, offline found only a closest match, the model declined, or it said it didn't know. | `[]`, except offline, where they are the passages quoted as the closest match. |

`coverage` is always present and counts sections, the backend's chunks.

## Endpoints

All paths are relative to `VITE_DOCKBRAIN_API_URL`. Request and response bodies are
JSON, except the upload.

### `GET /capabilities`

Returns `Capabilities`. The frontend validates file type and size locally using
`documentExtensions` and `maxDocumentBytes`. The proposed defaults are
`[".pdf", ".docx", ".txt", ".md", ".markdown"]` (what `rag/loader.py` reads) and
52428800 bytes (50 MB). `answerEngine` is a short human description, e.g. `"Gemini
gemini-3.6-flash (parts of the document are sent to Google)"` or `"Offline extractive
answers"`, mirroring the CLI's startup line.

### `POST /sessions` — upload and start processing

`multipart/form-data`:

| Field | Document | Codebase |
| --- | --- | --- |
| `kind` | `document` | `codebase` |
| `file` | the file | — |
| `name` | — | folder name |
| `manifest` | — | JSON `[{ "path": "src/app.py", "size": 1234 }, …]`, same order as `files` |
| `files` | — | one part per file. The filename is the relative path, but use `manifest` for paths because some servers strip directories from filenames. |

The frontend has already removed dependency and build folders (`node_modules`, `.git`,
`dist`, `.venv`, …), and sends at most 5000 files and 200 MB for a codebase.

`kind` must be `document`; `codebase` gets `415 unsupported` for now. The server checks
the file before accepting it: type by extension (`415`), size (`413`), and an empty file
(`422 unreadable`). Reading and indexing then happen in the background. A file that turns
out unreadable (damaged, scanned, encrypted, or without text) ends as `status: failed`, with
`error.code: "unreadable"` and a message naming the file.

Response `202` (or `200` if ready immediately), a **session resource**:

```json
{ "id": "s_8f2c", "kind": "document", "displayName": "report.pdf",
  "status": "processing", "stage": "indexing", "progress": 0.4,
  "message": "Reading page 12 of 61", "sectionCount": null, "notice": null }
```

- `status`: `processing` | `ready` | `failed`
- `stage`: `uploading` | `reading` | `indexing` | `ready` (optional)
- `progress`: 0–1, optional
- `error` (when `failed`): `{ "code": "unreadable", "message": "This PDF has no text layer…" }`

### `GET /sessions/{id}`

Returns the session resource. The frontend polls about every 800 ms while `status` is
`processing`.

### `DELETE /sessions/{id}`

Ends the session and deletes uploaded data. `204`. It must also work while the session
is still `processing`: stop the job, then delete the upload. Deleting an unknown or
already deleted session should return `204` or `404`; the frontend treats both as done.
The server returns `204` in both cases.

The frontend calls it when the person starts over, changes the document, or goes back,
and also when it abandons a session it never handed to the screens: processing was
cancelled, polling failed, or the job reported `failed`. That cleanup request is sent
without the cancelled request's abort signal. The frontend ignores failures, so the
server should also expire idle sessions.

If the upload itself is cancelled before `POST /sessions` responds, the frontend never
learns the session ID and cannot delete it. The server should discard an upload whose
request was aborted, and expire any session that is never polled.

### `GET /sessions/{id}/notes`

Returns `Notes` for a document session (`409 not_ready` while it is processing).

**With a model** (Ollama, Gemini or Claude), the request can take a minute or more. The
model is shown up to 40 passages spread through the document, without its reference list,
and writes the `summary`, `sections` and `suggestedQuestions`. Each point must give a quote
that is word for word from a passage it was shown, and most of its words must be in that
passage; points that fail are dropped, and so are summary sentences the passages don't
support. `title` is always the document's own. If the model fails or nothing passes, the
notes are built as below and `notice` says why; those notes aren't kept, so opening them
again tries the model again.

**Without a model**, or as that fallback, notes are built from the document's own sentences:

- `title`: the document's title line, or the file name without its extension.
- `summary`: the opening of the abstract, introduction or overview (the offline answer to
  "What is this document about?").
- `sections`: up to 8, in document order, named after the document's headings, without
  numbers or reference marks. Text without headings goes under "Key points".
- `points`: up to 3 per section. Each is a sentence quoted from the document, chosen for
  its rarer words, and cites the passage it came from through `sources`, whose entries
  carry `passageId`. Thank-yous, contents lines, code and sentences already in the summary
  are left out.
- `suggestedQuestions`: up to 3 "What is X?" questions for terms the document defines ("X
  is a …"), which offline answers handle well. The list may be empty.
- `demo`: `false`.

Successful notes are built once per session and dropped with it.

### `POST /sessions/{id}/questions`

Request `{ "question": "Which planet is the largest?" }` (at most 1000 characters).
Returns `Answer`. While the session is still processing: `409 not_ready`.

### `GET /sessions/{id}/passages/{passageId}`

Returns a whole passage with its neighbours, for showing more context around a citation:

```json
{ "passageId": 3, "text": "Jupiter is the largest planet. …", "section": "Jupiter",
  "previousId": 2, "nextId": 4 }
```

`section` is the heading the passage falls under, or `null`. `previousId` and `nextId`
are `null` at the ends. An unknown passage gets `404 not_found`.

### Quiz yourself (`quiz`)

Implemented in `server/quiz.py`, with generation and grading in `rag/quiz.py`. A session
can hold up to 20 quizzes; the oldest is dropped beyond that. Quizzes end with their
session (`DELETE /sessions/{id}` or idle expiry).

**Grounding.** Every question comes from one passage of the document and is answered by a
sentence quoted from it (`quote`). `citation` is that passage, with `passageId` for
`GET /sessions/{id}/passages/{passageId}`.

- **Offline**, or when the session has no AI provider, questions are fill-in-the-blank
  sentences from the document. The wrong options are other names or numbers from
  elsewhere in the document.
- **With a model (Ollama, Gemini or Claude)**, it is shown only the chosen passages, without the
  document's reference list, and can ask about any passage with a statement in it. Each of its
  questions is used only if all of the following hold:
  - its quote appears word for word in the passage;
  - the quote supports the correct option;
  - the quote supports no wrong option.

  Otherwise that question is dropped. A quote may leave out punctuation and reference
  marks, or be shortened with "…" if each piece is there, in order. If no question passes,
  the quiz is built offline.
- **If the provider fails** (rate limit, overload, network), the quiz is built offline
  rather than failing.

`notice` says when questions were rebuilt, or when fewer were possible than asked. The
`explanation` quotes the document and adds nothing else. The model's wording of a
question isn't checked beyond its answer and quote.

#### `POST /sessions/{id}/quizzes` — make a quiz

Request (both fields optional): `{ "count": 5, "revealAnswers": true }`. `count` is a whole
number from 1 to 10, default 5. `revealAnswers` defaults to `true`, which is what the
current frontend uses: it grades in the browser with `correctOptionId`. With `false`, the
answer fields (`correctOptionId`, `explanation`, `quote`, `citation`) are left out until
the quiz is graded.

Response `200`, a `Quiz`:

```json
{ "id": "qz_cCvjMGWti5Vq", "title": "Quiz: report.pdf", "demo": false,
  "engine": "Gemini gemini-3.6-flash", "answersRevealed": true,
  "notice": "Only 3 questions could be written from this document.",
  "questions": [
    { "id": "q1",
      "prompt": "Fill in the blank, from the document: “It has two small moons, Phobos and _____.”",
      "options": [{ "id": "a", "text": "Deimos" }, { "id": "b", "text": "Jupiter" }, { "id": "c", "text": "Uranus" }],
      "correctOptionId": "a",
      "explanation": "The document says: “It has two small moons, Phobos and Deimos.”",
      "quote": "It has two small moons, Phobos and Deimos.",
      "citation": { "index": 1, "excerpt": "Mars is called the Red Planet…", "section": "Mars", "passageId": 1 } }
  ] }
```

- `engine`: who wrote the questions. It is the provider's name, or "Built from the
  document's sentences".
- `notice`: omitted when there's nothing to say.
- `options`: 3 to 5 per question, with ids `a`, `b`, …
- **Fields `types.ts` doesn't declare yet:** `engine`, `notice`, `answersRevealed` and
  each question's `quote`. The current frontend ignores them. With `revealAnswers:
  false`, the answer fields the `Quiz` type marks as required are absent.

#### `GET /sessions/{id}/quizzes/{quizId}`

The same `Quiz` again. Hidden answers stay hidden.

#### `POST /sessions/{id}/quizzes/{quizId}/answers` — grade

Request `{ "answers": [{ "questionId": "q1", "optionId": "a" }] }`, with at most 50
answers. Questions without an answer count as wrong. A quiz can be graded any number of
times.

Response `200`:

```json
{ "quizId": "qz_cCvjMGWti5Vq", "score": { "correct": 1, "total": 3 },
  "results": [
    { "questionId": "q1", "selectedOptionId": "a", "correctOptionId": "a", "correct": true,
      "explanation": "The document says: “…”", "quote": "…", "citation": { "index": 1, "excerpt": "…", "passageId": 1 } }
  ] }
```

`selectedOptionId` is `null` for an unanswered question.

#### `DELETE /sessions/{id}/quizzes/{quizId}`

`204`, or `404 not_found` if the quiz is unknown or already deleted.

#### Quiz errors

All quiz errors use the standard error body.

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Malformed JSON, `count` outside 1–10, `revealAnswers` not a boolean, a malformed `answers` list, an unknown question or option, or a question answered twice |
| 404 | `not_found` | Unknown or ended session, or unknown quiz |
| 409 | `not_ready` | The document is still being read |
| 422 | `insufficient_content` | The document has no plain statements with names or numbers to ask about |

Provider failures don't produce an error here (see Grounding).

### Memory cards (`cards`)

Implemented in `server/cards.py`, with cards built in `rag/cards.py`.

**With a model** (Ollama, Gemini or Claude), it writes `question` cards from passages spread
through the document, and making a set can take up to a minute. Each card must give a quote
that is word for word from a passage it was shown (as for quizzes), and the quote must
support the answer. The question must make sense on its own, and mustn't contain the
answer. Cards that fail are dropped, and `answer` may be in the model's own words. If the
model fails or nothing passes, the set is built as below and `notice` says why.

**Without a model**, or as that fallback, each card comes from one sentence of one passage:

- **`definition`:** "X is a …" becomes the front "What is X?", and the back is the rest of
  the sentence ("a …"). X is a name, or a general term after "A" or "An"; "The result is
  a …" isn't used, because it means nothing without its context.
- **`cloze`:** a sentence with one name or number blanked out (`_____`) becomes the
  front, and the back is the blanked words.

On those cards, `answer` appears word for word in `quote`. On every card, `quote` comes from
`citation.excerpt`, the card's passage. `citation` has `passageId` but
no `score`. Headings, fragments, thank-yous and code aren't used. Neither are reference
lists, citations, book titles or lists of names, and a reference mark like `[12]` is never
the blank. Cards are spread through the document and kept in document order.

**Answers aren't sent early.** A card set carries only each card's front. The back comes
from a separate request when the learner reveals the card. Which cards a learner marks
"Know it" or "Review again" stays in the browser; the server doesn't store it.

A session keeps its 5 most recent card sets; older ones are dropped. Card sets end with
their session (`DELETE /sessions/{id}` or idle expiry).

#### `POST /sessions/{id}/cards` — make a card set

Request (optional): `{ "count": 10 }`. `count` is a whole number from 1 to 20, default 10.
An empty body uses the default.

Response `201`, a `CardSet` with fronts only:

```json
{ "id": "cs_Qy3m1TL0b8n2", "title": "report", "demo": false,
  "notice": "Only 4 cards could be made from this document.",
  "cards": [
    { "id": "c1", "kind": "definition", "prompt": "What is Harbor Lights?" },
    { "id": "c2", "kind": "cloze", "prompt": "Fill in the blank: “The lamp was first lit in 1871 by _____.”" }
  ] }
```

- `title`: the uploaded file's name without its extension.
- `notice`: `null` unless fewer cards could be made than asked for, or a model couldn't
  write them.

#### `GET /sessions/{id}/cards/{setId}`

The same `CardSet` again, fronts only.

#### `GET /sessions/{id}/cards/{setId}/answers/{cardId}` — reveal one card

Response `200`, a `CardAnswer`:

```json
{ "cardId": "c2", "answer": "Mara Quill",
  "quote": "The lamp was first lit in 1871 by Mara Quill.",
  "citation": { "index": 1, "excerpt": "Harbor Lights Handbook Overview Harbor Lights is a volunteer program … The lamp was first lit in 1871 by Mara Quill. …",
                "section": "Harbor Lights Handbook Overview", "passageId": 0 } }
```

The examples are from `tests/test_cards.py`'s invented handbook. Which word a cloze card
blanks out is picked at random, so a new set can blank a different one.

#### Memory card errors

All memory card errors use the standard error body.

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Malformed JSON, a body that isn't an object, or `count` that isn't a whole number from 1 to 20 |
| 404 | `not_found` | Unknown or ended session, unknown card set, or a card that isn't in the set |
| 409 | `not_ready` | The document is still being read (`retryable: true`) |
| 422 | `insufficient_content` | No sentence in the document can make a card. The message says what's missing, and the frontend shows it in place of a retry. |

### `GET /sessions/{id}/overview`

Returns `CodebaseOverview` for a codebase session.

## Errors

Any non-2xx response should carry:

```json
{ "error": { "code": "rate_limited", "message": "Gemini's daily free limit is used up. Try again tomorrow or use offline mode.", "retryable": true } }
```

| HTTP | `code` | Meaning |
| --- | --- | --- |
| 400 | `invalid_request` | Malformed JSON or multipart, or a missing or invalid field |
| 404 | `not_found` | Unknown or expired session, or unknown endpoint |
| 405 | `invalid_request` | The endpoint exists, but not for this method |
| 409 | `not_ready` | The session is still processing (`retryable: true`) |
| 413 | `too_large` | Upload over the limit |
| 415 | `unsupported` | File type not readable |
| 422 | `unreadable` | No text could be extracted (scanned, encrypted, damaged, empty) |
| 422 | `insufficient_content` | Too little usable text for a quiz or memory cards (see their sections) |
| 429 | `rate_limited` | Provider limit (the backend already distinguishes per-minute from daily limits) |
| 503 | `unavailable` | Provider overloaded or server not ready |
| other | `unknown` | Anything else |

Without a body, the adapter derives the code from the status and uses a generic message.
Network failures become `network`, and cancellations become `aborted`.

`retryable` is `true` when trying again later can help, for example per-minute rate limits,
an overloaded provider or `not_ready`. It is `false` otherwise, for example a used-up daily
limit, an unsupported file or invalid input. Provider messages from the answer engine are
passed on, without the CLI's "run with --offline" advice.

## Mapping to the Python backend

As implemented in `server/` on 2026-11-08 (the "Work needed" column is the original plan;
see the notes after the table):

| Contract | Existing backend | Work needed |
| --- | --- | --- |
| Load and index | `RAG(path, generator)` → `load_document`, `chunk_text`, `BM25Retriever` | Save the upload to a temp file; keep one `RAG` per session in memory. `sectionCount = len(rag.chunks)`. |
| `Answer.text` | `RAG.ask(question)` returns `(answer, hits)` | Use the answer string as is; `[n]` already refers to `hits[n-1]`. |
| `Answer.citations` | `hits`: `(Chunk, score)`; `Chunk.text`, `Chunk.sentences[*].section` | `excerpt = chunk.text`, `section` = the first non-empty sentence section, `score`. No page numbers: the PDF loader doesn't keep them. Add page tracking in `rag/loader.py` to supply `page`. |
| `Answer.origin` | Wording from `with_provenance`: "It wasn't in the information I was given, but" / "The rest wasn't…" / "I searched N of M sections…" / "No section of the document matched…"; offline `NOT_FOUND` and `UNSURE` | Better: have the generator return the origin it chose, rather than parsing text. Until then: cited and no label → `document`; cited and a "rest" label → `mixed`; label without citations → `general`; offline not-found or "declined" → `insufficient`. |
| `Answer.coverage` | `searched` and `sections` are computed inside `_OnlineGenerator.answer` | Return them; they're currently only used to build the label. |
| Quiz | `rag/quiz.py` (generation, checks, grading) and `server/quiz.py` (routes) | Implemented: see the Quiz section. Questions come from `rag.chunks`; with Gemini or Claude, the session's generator writes them through the same provider call settings. |
| Notes | `rag/notes.py` (a model's notes, or offline ones quoting the document) and `server/documents.py` (route) | Implemented: see `GET /sessions/{id}/notes`. |
| Memory cards | `rag/cards.py` (a model's cards, or offline ones, reusing `rag/quiz.py`'s checks) and `server/cards.py` (routes) | Implemented: see the Memory cards section. |
| Codebase overview | Not implemented | A new generation step, still citing excerpts. Codebase understanding is the deferred Version 4 in the root `CLAUDE.md`. Until then, report it as `unavailable`. |
| Capabilities | `pick_generator` decides the provider at startup | Report the chosen engine and limits. |

Implementation notes:

- **Origin:** the answer engines report the origin themselves (`last_origin` in
  `rag/generator.py`, exposed as `RAG.reply()`), so no text is parsed.
- **Coverage and citations:** these come from the same report.
- **Page numbers:** still missing. The PDF loader doesn't track pages.
- **Sessions:** there is one `rag.RAG` per session, built in the background (`server/sessions.py`).

The frontend already mirrors the backend's wording and answer-origin rules (see
`src/fixtures/sampleDocument.ts`), so live answers render the same way as the demo ones.
