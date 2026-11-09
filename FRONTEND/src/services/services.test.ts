import { describe, expect, it, vi } from 'vitest';
import { MockDockBrainService } from './mockService';
import { HttpDockBrainService } from './httpService';
import { createService, simulatedFailures } from './index';
import { ServiceError, offers, type Capabilities } from './types';

describe('MockDockBrainService', () => {
  it('never reads the selected file and labels every result as demo', async () => {
    const file = new File(['private contents'], 'secret.pdf');
    const reads = [
      vi.spyOn(file, 'text'),
      vi.spyOn(file, 'arrayBuffer'),
      vi.spyOn(file, 'slice'),
      vi.spyOn(FileReader.prototype, 'readAsArrayBuffer'),
      vi.spyOn(FileReader.prototype, 'readAsText'),
      vi.spyOn(FileReader.prototype, 'readAsDataURL'),
    ];
    const service = new MockDockBrainService({ latencyMs: 0 });
    const progress = vi.fn();

    const session = await service.openSource({ kind: 'document', file }, { onProgress: progress });
    const [notes, answer, quiz] = await Promise.all([
      service.getNotes(session.id),
      service.ask(session.id, 'Which planet is the largest?'),
      service.getQuiz(session.id),
    ]);

    reads.forEach((spy) => expect(spy).not.toHaveBeenCalled());
    expect(session).toMatchObject({ demo: true, displayName: 'secret.pdf', notice: expect.stringContaining('was not read') });
    expect(progress).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('Nothing is uploaded') }));
    expect([notes.demo, answer.demo, quiz.demo]).toEqual([true, true, true]);
  });

  it('answers each origin the way the backend labels them', async () => {
    const service = new MockDockBrainService({ latencyMs: 0 });
    const { id } = await service.openSource({ kind: 'document', file: new File(['x'], 'a.txt') });
    const origin = async (q: string) => (await service.ask(id, q)).origin;
    expect(await origin('Which planet is the largest?')).toBe('document');
    expect(await origin('How many moons does Mars have, and who discovered them?')).toBe('mixed');
    expect(await origin('Who discovered Neptune?')).toBe('general');
    expect(await origin('How far is Mars from the Sun?')).toBe('insufficient');
    const general = await service.ask(id, 'Who discovered Neptune?');
    expect(general.text).toMatch(/^It wasn't in the information I was given, but/);
    expect(general.citations).toEqual([]);
  });

  it('fails the configured number of times, then succeeds', async () => {
    const service = new MockDockBrainService({ latencyMs: 0, failures: { ask: 1 } });
    const { id } = await service.openSource({ kind: 'document', file: new File(['x'], 'a.txt') });
    await expect(service.ask(id, 'Pluto?')).rejects.toMatchObject({ code: 'network', retryable: true });
    await expect(service.ask(id, 'Pluto?')).resolves.toMatchObject({ origin: 'document' });
  });

  it('rejects requests for closed or mismatched sessions', async () => {
    const service = new MockDockBrainService({ latencyMs: 0 });
    const { id } = await service.openSource({ kind: 'codebase', name: 'proj', files: [] });
    await expect(service.getNotes(id)).rejects.toBeInstanceOf(ServiceError);
    await service.closeSession(id);
    await expect(service.getCodebaseOverview(id)).rejects.toMatchObject({ code: 'not_found' });
  });

  it('makes sample memory cards whose answers come only on reveal, each quoting its passage', async () => {
    const service = new MockDockBrainService({ latencyMs: 0 });
    const { id } = await service.openSource({ kind: 'document', file: new File(['x'], 'a.txt') });
    const set = await service.getCards(id);
    expect(set.demo).toBe(true);
    expect(set.cards.length).toBeGreaterThan(1);
    for (const card of set.cards) {
      expect(Object.keys(card).sort()).toEqual(['id', 'kind', 'prompt']);
      const back = await service.revealCard(id, set.id, card.id);
      expect(back.cardId).toBe(card.id);
      expect(back.quote).toContain(back.answer);
      expect(back.citation.excerpt).toContain(back.quote);
      expect(card.prompt).not.toContain(back.answer);
    }
    await expect(service.revealCard(id, set.id, 'c999')).rejects.toMatchObject({ code: 'not_found' });
    expect((await service.getCards(id, { count: 2 })).cards).toHaveLength(2);
  });

  it('can be cancelled', async () => {
    const service = new MockDockBrainService({ latencyMs: 50 });
    const controller = new AbortController();
    const opening = service.openSource({ kind: 'document', file: new File(['x'], 'a.txt') }, { signal: controller.signal });
    controller.abort();
    await expect(opening).rejects.toMatchObject({ code: 'aborted' });
  });
});

describe('service selection', () => {
  it('uses demo mode unless an API URL is configured', () => {
    expect(createService({}, '').mode).toBe('demo');
    expect(createService({ VITE_DOCKBRAIN_API_URL: 'http://localhost:8000/api/v1' }, '').mode).toBe('live');
  });

  it('reads simulated failures from the URL', () => {
    expect(simulatedFailures('?simulate=ask-error,open-error&simulate=bogus')).toEqual({ ask: 1, open: 1 });
    expect(simulatedFailures('?simulate=cards-error')).toEqual({ cards: 1 });
  });
});

describe('offers', () => {
  const capabilities = { mode: 'live', notes: 'available', ask: 'available', quiz: 'unavailable', codebase: 'demo' } as Capabilities;

  it('offers everything until capabilities arrive, then only what they list as available or demo', () => {
    expect(offers(null, 'cards')).toBe(true);
    expect(offers(capabilities, 'notes')).toBe(true);
    expect(offers(capabilities, 'codebase')).toBe(true);
    expect(offers(capabilities, 'quiz')).toBe(false);
  });

  it('does not offer memory cards on a server whose capabilities predate them', () => {
    expect(offers(capabilities, 'cards')).toBe(false);
    expect(offers({ ...capabilities, cards: 'available' }, 'cards')).toBe(true);
  });
});

describe('HttpDockBrainService (draft adapter for the proposed API)', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

  it('uploads a document, polls until ready, and never marks live results as demo', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json({ id: 's1', kind: 'document', displayName: 'a.pdf', status: 'processing', stage: 'indexing' }, 202))
      .mockResolvedValueOnce(json({ id: 's1', kind: 'document', displayName: 'a.pdf', status: 'ready', sectionCount: 12 }))
      .mockResolvedValueOnce(json({ id: 'a1', question: 'Q', text: 'A [1]', origin: 'document', citations: [{ index: 1, excerpt: 'E', page: 3 }] }));
    const service = new HttpDockBrainService({ baseUrl: 'http://api.test/v1/', fetchImpl, pollIntervalMs: 0 });

    const stages: string[] = [];
    const session = await service.openSource({ kind: 'document', file: new File(['x'], 'a.pdf') }, { onProgress: (p) => stages.push(p.stage) });
    expect(session).toMatchObject({ id: 's1', demo: false, sectionCount: 12 });
    expect(stages).toEqual(['uploading', 'indexing', 'ready']);

    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe('http://api.test/v1/sessions');
    expect(init?.method).toBe('POST');
    expect((init?.body as FormData).get('kind')).toBe('document');

    const answer = await service.ask('s1', 'Q');
    expect(fetchImpl.mock.calls[2]![0]).toBe('http://api.test/v1/sessions/s1/questions');
    expect(answer).toMatchObject({ demo: false, citations: [{ page: 3 }] });
  });

  it('maps HTTP errors and network failures to ServiceError codes', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json({ error: { code: 'rate_limited', message: 'Daily limit reached.' } }, 429))
      .mockResolvedValueOnce(new Response('nope', { status: 413 }))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const service = new HttpDockBrainService({ baseUrl: 'http://api.test', fetchImpl });

    await expect(service.ask('s1', 'Q')).rejects.toMatchObject({ code: 'rate_limited', message: 'Daily limit reached.' });
    await expect(service.getNotes('s1')).rejects.toMatchObject({ code: 'too_large' });
    await expect(service.getCapabilities()).rejects.toMatchObject({ code: 'network' });
  });

  it('creates a card set, then fetches one card’s answer at a time', async () => {
    const front = { id: 'cs_1', title: 'notes', cards: [{ id: 'c1', kind: 'cloze', prompt: 'Fill in the blank: “_____ is red.”' }] };
    const back = { cardId: 'c1', answer: 'Mars', quote: 'Mars is red.', citation: { index: 1, excerpt: 'Mars is red.', passageId: 4 } };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValueOnce(json(front, 201)).mockResolvedValueOnce(json(back));
    const service = new HttpDockBrainService({ baseUrl: 'http://api.test', fetchImpl });

    const set = await service.getCards('s 1');
    expect(set).toMatchObject({ id: 'cs_1', demo: false, notice: null, cards: front.cards });
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe('http://api.test/sessions/s%201/cards');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(init?.body as string)).toEqual({ count: 10 });

    await expect(service.revealCard('s 1', 'cs_1', 'c/1')).resolves.toEqual(back);
    expect(fetchImpl.mock.calls[1]![0]).toBe('http://api.test/sessions/s%201/cards/cs_1/answers/c%2F1');
  });

  it('passes on the server’s reason when a document has too little to make cards from', async () => {
    const message = 'This document doesn’t have enough plain statements to make memory cards from.';
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json({ error: { code: 'insufficient_content', message, retryable: false } }, 422))
      .mockResolvedValueOnce(json({}, 422));
    const service = new HttpDockBrainService({ baseUrl: 'http://api.test', fetchImpl });
    await expect(service.getCards('s1')).rejects.toMatchObject({ code: 'insufficient_content', message, retryable: false });
    await expect(service.getCards('s1')).rejects.toMatchObject({ code: 'unreadable' });
  });

  it('reports a failed processing job with the server’s reason', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValueOnce(
      json({ id: 's1', kind: 'document', displayName: 'scan.pdf', status: 'failed', error: { code: 'unreadable', message: 'No text found.' } }),
    );
    const service = new HttpDockBrainService({ baseUrl: 'http://api.test', fetchImpl });
    await expect(service.openSource({ kind: 'document', file: new File(['x'], 'scan.pdf') })).rejects.toMatchObject({
      code: 'unreadable',
      message: 'No text found.',
    });
    expect(fetchImpl).toHaveBeenLastCalledWith('http://api.test/sessions/s1', expect.objectContaining({ method: 'DELETE' }));
  });

  describe('ends a server session the app will never receive', () => {
    const processing = { id: 's 9', kind: 'document', displayName: 'a.pdf', status: 'processing' };
    const deletes = (fetchImpl: ReturnType<typeof vi.fn<typeof fetch>>) =>
      fetchImpl.mock.calls.filter(([, init]) => init?.method === 'DELETE');

    it('when processing is cancelled while waiting to poll', async () => {
      const fetchImpl = vi.fn<typeof fetch>(async (_url, init) => (init?.method === 'DELETE' ? new Response(null, { status: 204 }) : json(processing, 202)));
      const service = new HttpDockBrainService({ baseUrl: 'http://api.test', fetchImpl, pollIntervalMs: 60_000 });
      const controller = new AbortController();
      const opening = service.openSource({ kind: 'document', file: new File(['x'], 'a.pdf') }, {
        signal: controller.signal,
        onProgress: (progress) => {
          if (progress.stage === 'indexing') queueMicrotask(() => controller.abort());
        },
      });

      await expect(opening).rejects.toMatchObject({ code: 'aborted' });
      expect(deletes(fetchImpl)).toHaveLength(1);
      const [url, init] = deletes(fetchImpl)[0]!;
      expect(url).toBe('http://api.test/sessions/s%209');
      // The cleanup must not reuse the cancelled request's signal, or it would never be sent.
      expect(init?.signal?.aborted).not.toBe(true);
    });

    it('when processing is cancelled during a status request', async () => {
      const controller = new AbortController();
      const fetchImpl = vi.fn<typeof fetch>(async (_url, init) => {
        if (init?.method === 'DELETE') return new Response(null, { status: 204 });
        if (init?.method === 'POST') return json(processing, 202);
        controller.abort();
        throw new DOMException('The operation was aborted.', 'AbortError');
      });
      const service = new HttpDockBrainService({ baseUrl: 'http://api.test', fetchImpl, pollIntervalMs: 0 });

      await expect(service.openSource({ kind: 'document', file: new File(['x'], 'a.pdf') }, { signal: controller.signal })).rejects.toMatchObject({ code: 'aborted' });
      expect(deletes(fetchImpl)).toHaveLength(1);
    });

    it('when processing finishes just after it was cancelled', async () => {
      const controller = new AbortController();
      const fetchImpl = vi.fn<typeof fetch>(async (_url, init) => {
        if (init?.method === 'DELETE') return new Response(null, { status: 204 });
        controller.abort(); // the response arrives anyway
        return json({ ...processing, status: 'ready' });
      });
      const service = new HttpDockBrainService({ baseUrl: 'http://api.test', fetchImpl });

      await expect(service.openSource({ kind: 'document', file: new File(['x'], 'a.pdf') }, { signal: controller.signal })).rejects.toMatchObject({ code: 'aborted' });
      expect(deletes(fetchImpl)).toHaveLength(1);
    });

    it('but not when the upload itself failed, since no session exists', async () => {
      const fetchImpl = vi.fn<typeof fetch>().mockResolvedValueOnce(json({ error: { code: 'too_large', message: 'Too big.' } }, 413));
      const service = new HttpDockBrainService({ baseUrl: 'http://api.test', fetchImpl });
      await expect(service.openSource({ kind: 'document', file: new File(['x'], 'a.pdf') })).rejects.toMatchObject({ code: 'too_large' });
      expect(deletes(fetchImpl)).toHaveLength(0);
    });
  });
});
