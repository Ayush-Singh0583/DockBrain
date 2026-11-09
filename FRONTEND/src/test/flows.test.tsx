import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import { liveService, openDocument, pdf, renderApp, startSlowFolderDrop } from './renderApp';
import { RobotMascot } from '../components/robot/RobotMascot';
import { ServiceError } from '../services/types';

describe('welcome and selection', () => {
  it('offers the three activities and leads each to the right picker', async () => {
    const { user } = renderApp();
    expect(screen.getByText('Hi, I’m DockBrain.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'What would you like to explore today?' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Understand a codebase/ }));
    expect(screen.getByRole('heading', { name: 'Put your project folder here' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Back' }));

    await user.click(screen.getByRole('button', { name: /Quiz yourself/ }));
    expect(screen.getByRole('heading', { name: 'Put your document here' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Build my quiz/ })).toBeInTheDocument();
  });

  it('shows the chosen file, rejects unsupported ones, and supports replace and remove', async () => {
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: /Learn from a document/ }));

    await user.click(screen.getByRole('button', { name: /Open document/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a document first.');

    await user.upload(screen.getByTestId('document-input'), new File(['png'], 'photo.png', { type: 'image/png' }));
    expect(screen.getByRole('alert')).toHaveTextContent('“photo.png” isn’t a supported type');

    await user.upload(screen.getByTestId('document-input'), pdf('Guide.pdf', 2048));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument(); // error cleared by a valid choice
    expect(screen.getByText('Guide.pdf')).toBeInTheDocument();
    expect(screen.getByText(/PDF · 2 KB · selected on this device/)).toBeInTheDocument();
    expect(screen.getByText(/isn’t uploaded or read/)).toBeInTheDocument();

    await user.upload(screen.getByTestId('document-input'), new File(['# hi'], 'notes.md'));
    expect(screen.getByText('notes.md')).toBeInTheDocument();
    expect(screen.queryByText('Guide.pdf')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Remove notes.md' }));
    expect(screen.getByRole('button', { name: 'Choose a file' })).toBeInTheDocument();
  });

  it('keeps the document when switching to the quiz, but not when switching to a codebase', async () => {
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: /Learn from a document/ }));
    await user.upload(screen.getByTestId('document-input'), pdf('Keep.pdf'));
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: /Quiz yourself/ }));
    expect(screen.getByText('Keep.pdf')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: /Understand a codebase/ }));
    expect(screen.queryByText('Keep.pdf')).not.toBeInTheDocument();
  });

  it('reports a processing failure and recovers on retry', async () => {
    const { user } = renderApp({ failures: { open: 1 } });
    await openDocument(user);
    expect(await screen.findByText('Couldn’t open this')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Try again/ }));
    expect(await screen.findByRole('heading', { name: 'The Solar System' })).toBeInTheDocument();
  });
});

describe('learning workspace', () => {
  it('labels demo notes as sample content and keeps the selected file visible', async () => {
    const { user } = renderApp();
    await openDocument(user);
    expect(await screen.findByRole('heading', { name: 'The Solar System' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Fruit-Guide.pdf' })).toBeInTheDocument();
    expect(screen.getByText(/not analysed \(demo\)/)).toBeInTheDocument();
    expect(screen.getByText(/not “Fruit-Guide.pdf”, which wasn’t read/)).toBeInTheDocument();
  });

  it('opens the matching source when a citation number is pressed', async () => {
    const { user } = renderApp();
    await openDocument(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    const toggle = screen.getByRole('button', { name: 'Sources (5)' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(screen.getAllByRole('button', { name: 'Show source 3' })[0]!);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const source = screen.getByText(/It has a mass more than twice that/).closest('li')!;
    expect(source).toHaveAttribute('data-highlight', 'true');
    await waitFor(() => expect(source).toHaveFocus());
  });

  it('supports arrow keys between tabs', async () => {
    const { user } = renderApp();
    await openDocument(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    screen.getByRole('tab', { name: 'Notes' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Ask' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Ask' })).toHaveFocus();
    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'Cards' })).toHaveAttribute('aria-selected', 'true');
  });

  it('distinguishes document, mixed, general and insufficient answers', async () => {
    const { user } = renderApp();
    await openDocument(user);
    await user.click(screen.getByRole('tab', { name: 'Ask' }));

    const input = screen.getByLabelText('Your question');
    let asked = 0;
    const ask = async (question: string) => {
      await user.type(input, `${question}{Enter}`);
      asked += 1;
      await waitFor(() => expect(screen.getAllByRole('article', { name: /^Answer/ })).toHaveLength(asked));
    };

    await ask('Which planet is the largest?');
    await ask('How many moons does Mars have, and who discovered them?');
    await ask('Who discovered Neptune?');
    await ask('How far is Mars from the Sun?');

    const answers = screen.getAllByRole('article');
    expect(answers.map((a) => a.getAttribute('aria-label'))).toEqual([
      'Answer, from the document',
      'Answer, partly from the document',
      'Answer, general knowledge',
      'Answer, not enough evidence',
    ]);
    expect(within(answers[0]!).getByText(/searched all 5 sections/)).toBeInTheDocument();
    expect(within(answers[1]!).getByText('General knowledge:', { exact: false })).toBeInTheDocument();
    expect(within(answers[2]!).queryByRole('button', { name: /Sources/ })).not.toBeInTheDocument();

    await user.click(within(answers[0]!).getByRole('button', { name: 'Sources (1)' }));
    expect(within(answers[0]!).getByText('Section “The Solar System”')).toBeInTheDocument();
    expect(within(answers[0]!).queryByText(/Page/)).not.toBeInTheDocument(); // no page data supplied
  });

  it('asks for text before sending an empty question', async () => {
    const { user } = renderApp();
    await openDocument(user);
    await user.click(screen.getByRole('tab', { name: 'Ask' }));
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Type a question first.');
    expect(screen.getByLabelText('Your question')).toHaveAttribute('aria-invalid', 'true');
  });

  it('shows a failed answer with a working retry', async () => {
    const { user } = renderApp({ failures: { ask: 1 } });
    await openDocument(user);
    await user.click(screen.getByRole('tab', { name: 'Ask' }));
    await user.click(await screen.findByRole('button', { name: 'Which planet is the largest?' }));
    expect(await screen.findByText('Couldn’t get an answer')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Try again/ }));
    expect(await screen.findByRole('article', { name: 'Answer, from the document' })).toBeInTheDocument();
  });

  it('confirms before starting over when questions would be lost', async () => {
    const { user } = renderApp();
    await openDocument(user);
    await user.click(screen.getByRole('tab', { name: 'Ask' }));
    await user.click(await screen.findByRole('button', { name: 'Which planet is the largest?' }));
    await screen.findByRole('article', { name: 'Answer, from the document' });

    const startOver = screen.getByRole('button', { name: 'Start over' });
    await user.click(startOver);
    const dialog = screen.getByRole('dialog', { name: 'Start over and clear “Fruit-Guide.pdf”?' });
    const keep = within(dialog).getByRole('button', { name: 'Keep working' });
    expect(keep).toHaveFocus(); // the safe choice comes first
    await user.click(keep);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(startOver).toHaveFocus();
    expect(screen.getByRole('article', { name: 'Answer, from the document' })).toBeInTheDocument();

    await user.click(startOver);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Clear and start over' }));
    expect(screen.getByRole('heading', { name: 'What would you like to explore today?' })).toBeInTheDocument();
  });

  it('starts over at once when there is nothing to lose', async () => {
    const { user } = renderApp();
    await openDocument(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    await user.click(screen.getByRole('button', { name: 'Start over' }));
    expect(screen.getByRole('heading', { name: 'What would you like to explore today?' })).toBeInTheDocument();
  });

  it('confirms before changing the document when work would be lost, and Esc keeps it', async () => {
    const { user } = renderApp();
    await openDocument(user);
    await user.click(screen.getByRole('tab', { name: 'Ask' }));
    await user.click(await screen.findByRole('button', { name: 'Which planet is the largest?' }));
    await screen.findByRole('article', { name: 'Answer, from the document' });

    const change = screen.getByRole('button', { name: 'Change document' });
    await user.click(change);
    const dialog = screen.getByRole('dialog', { name: 'Change document and clear “Fruit-Guide.pdf”?' });
    await act(async () => void dialog.dispatchEvent(new Event('cancel', { cancelable: true })));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(change).toHaveFocus();

    await user.click(change);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Clear and change document' }));
    expect(screen.getByRole('button', { name: /Open document/ })).toBeInTheDocument();
  });

  it('changes the document at once when there is nothing to lose', async () => {
    const { user } = renderApp();
    await openDocument(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    await user.click(screen.getByRole('button', { name: 'Change document' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Open document/ })).toBeInTheDocument();
  });
});

describe('quiz', () => {
  it('explains when a document has too little to quiz on, without a retry that can’t help', async () => {
    const service = liveService({ quiz: 'available' });
    const message = 'This document doesn’t have enough plain statements to write questions from.';
    service.getQuiz.mockRejectedValue(new ServiceError('insufficient_content', message, false));
    const { user } = renderApp({}, service);
    await openDocument(user, /Quiz yourself/);

    expect(await screen.findByText('Not enough here to write a quiz')).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Try again/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Choose another document' }));
    expect(screen.getByRole('button', { name: /Build my quiz/ })).toBeInTheDocument();
  });

  it('still offers a retry when the quiz failed for a reason that can pass', async () => {
    const service = liveService({ quiz: 'available' });
    const getQuiz = service.getQuiz.getMockImplementation()!;
    service.getQuiz.mockRejectedValueOnce(new ServiceError('network', 'DockBrain couldn’t be reached.')).mockImplementation(getQuiz);
    const { user } = renderApp({}, service);
    await openDocument(user, /Quiz yourself/);
    expect(await screen.findByText('Quiz isn’t available')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Try again/ }));
    expect(await screen.findByText('Question 1 of 5')).toBeInTheDocument();
  });

  it('runs one question at a time with feedback, results and retry', async () => {
    const { user } = renderApp();
    await openDocument(user, /Quiz yourself/);
    expect(await screen.findByText('Question 1 of 5')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Check answer' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose an answer first.');

    await user.click(screen.getByLabelText(/460 million years ago/)); // wrong
    await user.click(screen.getByRole('button', { name: 'Check answer' }));
    expect(screen.getByText('Not quite.')).toBeInTheDocument();
    expect(screen.getByText('4.6 billion years ago', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getByLabelText(/460 million years ago/)).toBeDisabled();

    const correct = ['Neptune', 'Iron oxide on its surface', 'A storm on Jupiter', 'It was reclassified as a dwarf planet'];
    for (const option of correct) {
      await user.click(screen.getByRole('button', { name: /Next question/ }));
      await user.click(screen.getByLabelText(new RegExp(option)));
      await user.click(screen.getByRole('button', { name: 'Check answer' }));
      expect(screen.getByText('Correct!')).toBeInTheDocument();
    }
    await user.click(screen.getByRole('button', { name: /See results/ }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'You got 4 of 5 right' })).toHaveFocus());

    await user.click(screen.getByRole('button', { name: /Retry quiz/ }));
    expect(screen.getByText('Question 1 of 5')).toBeInTheDocument();
    expect(screen.getByLabelText(/460 million years ago/)).not.toBeChecked();
  });

  it('shows an error with retry when the quiz cannot be loaded', async () => {
    const { user } = renderApp({ failures: { quiz: 1 } });
    await openDocument(user, /Quiz yourself/);
    expect(await screen.findByText('Quiz isn’t available')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Try again/ }));
    expect(await screen.findByText('Question 1 of 5')).toBeInTheDocument();
  });
});

describe('memory cards', () => {
  afterEach(() => vi.restoreAllMocks());

  const prompt = () => document.querySelector('.memory-card__prompt')!.textContent;
  const openCards = async (options: Parameters<typeof renderApp>[0] = {}, service?: Parameters<typeof renderApp>[1]) => {
    const rendered = renderApp(options, service);
    await openDocument(rendered.user, /Memory cards/);
    await screen.findByText('Card 1 of 5');
    return rendered;
  };

  it('shows one sample card at a time, labelled as a sample, with its answer only after revealing it', async () => {
    const { user } = await openCards();
    expect(screen.getByRole('tab', { name: 'Cards' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Sample content')).toBeVisible();
    expect(screen.getByText(/These cards are about DockBrain’s built-in sample.txt .* not “Fruit-Guide.pdf”, which wasn’t read/)).toBeInTheDocument();
    expect(screen.getByText('Sample card')).toBeVisible();

    expect(prompt()).toMatch(/formed about blank years ago/);
    expect(screen.queryByText('4.6 billion')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Know it/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Show answer/ }));
    expect(await screen.findByText('4.6 billion', { selector: '.memory-card__answer' })).toBeVisible();
    expect(document.querySelector('.memory-card__quote blockquote')!.textContent).toBe(
      'The Solar System formed about 4.6 billion years ago from the gravitational collapse of a giant molecular cloud.',
    );
    expect(document.querySelector('.memory-card__quote mark')!.textContent).toBe('4.6 billion');
    expect(document.querySelector('.memory-card__prompt')).toBeNull(); // the quote says the same as a cloze front
    await user.click(screen.getByRole('button', { name: /Passage \(1\)/ }));
    expect(screen.getByText(/Most of its mass is in the Sun/)).toBeVisible();
  });

  it('announces each card, and then its answer, to screen readers', async () => {
    const { user } = await openCards();
    const status = () => document.querySelector('.cards__announce')!.textContent;
    expect(status()).toMatch(/^Card 1 of 5: Fill in the blank: .*formed about blank years ago/);
    await user.click(screen.getByRole('button', { name: /Next/ }));
    expect(status()).toMatch(/^Card 2 of 5: .*Uranus and blank are ice giants/);
    await user.click(screen.getByRole('button', { name: /Show answer/ }));
    await waitFor(() => expect(status()).toBe('Answer: Neptune'));
  });

  it('requests each answer only when its card is revealed, once', async () => {
    const service = liveService({ cards: 'available' });
    const { user } = await openCards({}, service);
    // A live session can still be served sample cards: labelled, without saying the file went unread.
    expect(screen.getByText(/These cards are built-in samples .* not about “Fruit-Guide.pdf”/)).toBeInTheDocument();
    expect(screen.queryByText(/wasn’t read/)).not.toBeInTheDocument();
    expect(service.getCards).toHaveBeenCalledTimes(1);
    expect(service.revealCard).not.toHaveBeenCalled();
    const flip = screen.getByRole('button', { name: /Show answer/ });
    await user.click(flip);
    await screen.findByText('4.6 billion', { selector: '.memory-card__answer' });
    await user.click(screen.getByRole('button', { name: /Show the question/ }));
    await user.click(screen.getByRole('button', { name: /Show answer/ }));
    expect(service.revealCard).toHaveBeenCalledTimes(1);
    expect(service.revealCard).toHaveBeenCalledWith(expect.any(String), 'sample-cards', 'c1', expect.anything());
  });

  it('moves between cards with Previous and Next, which stop at the ends', async () => {
    const { user } = await openCards();
    const previous = screen.getByRole('button', { name: /Previous/ });
    const next = screen.getByRole('button', { name: /Next/ });
    expect(previous).toBeDisabled();
    await user.click(next);
    expect(screen.getByText('Card 2 of 5')).toBeInTheDocument();
    expect(prompt()).toMatch(/Uranus and blank are ice giants/);
    await user.click(screen.getByRole('button', { name: /Show answer/ }));
    await user.click(previous);
    expect(screen.getByText('Card 1 of 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Show answer/ })).toBeInTheDocument(); // a new card starts face up
    for (let i = 0; i < 4; i++) await user.click(next);
    expect(screen.getByText('Card 5 of 5')).toBeInTheDocument();
    expect(next).toBeDisabled();
  });

  it('works from the keyboard: Space flips, arrows move, K and R mark', async () => {
    const { user } = await openCards();
    const flip = screen.getByRole('button', { name: /Show answer/ });
    flip.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByText('Card 2 of 5')).toBeInTheDocument();
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByText('Card 1 of 5')).toBeInTheDocument();

    await user.keyboard('k'); // marking needs the answer to have been seen
    expect(screen.getByText('0 known · 0 to review')).toBeInTheDocument();
    await user.keyboard(' ');
    await screen.findByText('4.6 billion', { selector: '.memory-card__answer' });
    await user.keyboard('k');
    expect(screen.getByText('Card 2 of 5')).toBeInTheDocument();
    expect(screen.getByText('1 known · 0 to review')).toBeInTheDocument();
    await user.keyboard('{Enter}');
    await screen.findByText('Neptune', { selector: '.memory-card__answer' });
    await user.keyboard('r');
    expect(screen.getByText('1 known · 1 to review')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Cards marked' })).toHaveAttribute('aria-valuenow', '2');
  });

  it('takes shortcuts without focus being in the card, but leaves other keys’ owners alone', async () => {
    const { user } = await openCards();
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard(' ');
    await screen.findByText('4.6 billion', { selector: '.memory-card__answer' });
    await user.keyboard('r');
    expect(screen.getByText('0 known · 1 to review')).toBeInTheDocument();

    // A focused button acts for itself: Space on Next moves on once, without flipping.
    screen.getByRole('button', { name: /Next/ }).focus();
    await user.keyboard(' ');
    expect(screen.getByText('Card 3 of 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Show answer/ })).toBeInTheDocument();

    // The tab strip keeps its own arrow keys.
    screen.getByRole('tab', { name: 'Cards' }).focus();
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('tab', { name: 'Quiz' })).toHaveAttribute('aria-selected', 'true');
    await user.click(screen.getByRole('tab', { name: 'Cards' }));
    expect(screen.getByText('Card 3 of 5')).toBeInTheDocument();

    // Away from the Cards tab, the shortcuts are off.
    await user.click(screen.getByRole('tab', { name: 'Notes' }));
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard('{ArrowRight}');
    await user.click(screen.getByRole('tab', { name: 'Cards' }));
    expect(screen.getByText('Card 3 of 5')).toBeInTheDocument();
  });

  it('keeps the question on the back of a definition card, and shows a card’s earlier mark', async () => {
    const { user } = await openCards();
    await user.click(screen.getByRole('button', { name: /Show answer/ }));
    await user.click(await screen.findByRole('button', { name: /Know it/ }));
    expect(screen.getByRole('button', { name: /Show answer/ })).toHaveFocus(); // not lost with the button that was pressed
    await user.click(screen.getByRole('button', { name: /Previous/ }));
    expect(screen.getByText('Marked “Know it”')).toBeVisible();
    await user.click(screen.getByRole('button', { name: /Next/ }));
    await user.click(screen.getByRole('button', { name: /Next/ }));
    expect(prompt()).toBe('What is Jupiter?');
    await user.click(screen.getByRole('button', { name: /Show answer/ }));
    await screen.findByText('the largest planet', { selector: '.memory-card__answer' });
    expect(prompt()).toBe('What is Jupiter?');
  });

  it('shuffles the cards and starts again from the top', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    const { user } = await openCards();
    await user.click(screen.getByRole('button', { name: /Next/ }));
    await user.click(screen.getByRole('button', { name: /Shuffle/ }));
    // With random() = 0 the shuffle moves each card down one place: c2, c3, c4, c5, c1.
    expect(screen.getByText('Card 1 of 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Show answer/ })).toHaveFocus(); // Space flips, not shuffles again
    expect(prompt()).toMatch(/Uranus and blank/);
    await user.click(screen.getByRole('button', { name: /Next/ }));
    expect(prompt()).toBe('What is Jupiter?');
  });

  it('sums up a round, then reviews only the cards marked “Review again”', async () => {
    const { user } = await openCards();
    for (const verdict of ['Know it', 'Review again', 'Know it', 'Review again', 'Know it']) {
      await user.click(screen.getByRole('button', { name: /Show answer/ }));
      await user.click(await screen.findByRole('button', { name: new RegExp(verdict) }));
    }
    expect(await screen.findByRole('heading', { name: 'You know 3 of 5 cards' })).toBeInTheDocument();
    expect(screen.getByText('2 cards are marked “Review again”.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Review the 2 again/ }));
    expect(screen.getByText('Card 1 of 2')).toBeInTheDocument();
    expect(prompt()).toMatch(/Uranus and blank/);
    expect(screen.getByText('0 known · 0 to review')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Next/ }));
    expect(prompt()).toMatch(/Phobos and blank/);
  });

  it('asks before Start over once cards have been marked', async () => {
    const { user } = await openCards();
    await user.click(screen.getByRole('button', { name: /Show answer/ }));
    await user.click(await screen.findByRole('button', { name: /Know it/ }));
    await user.click(screen.getByRole('button', { name: /Start over/ }));
    expect(screen.getByRole('heading', { level: 1, name: 'Fruit-Guide.pdf' })).toBeInTheDocument();
  });

  it('explains when a document has too little to make cards from, without a retry that can’t help', async () => {
    const service = liveService({ cards: 'available' });
    const message = 'This document doesn’t have enough plain statements to make memory cards from.';
    service.getCards.mockRejectedValue(new ServiceError('insufficient_content', message, false));
    const { user } = renderApp({}, service);
    await openDocument(user, /Memory cards/);

    expect(await screen.findByText('Not enough here to make cards')).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Try again/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Read the notes' }));
    expect(screen.getByRole('tab', { name: 'Notes' })).toHaveAttribute('aria-selected', 'true');
    await user.click(screen.getByRole('tab', { name: 'Cards' }));
    await user.click(screen.getByRole('button', { name: 'Choose another document' }));
    expect(screen.getByRole('button', { name: /Make my cards/ })).toBeInTheDocument();
  });

  it('offers a retry when the cards or an answer fail to load', async () => {
    const service = liveService({ cards: 'available' });
    const getCards = service.getCards.getMockImplementation()!;
    const revealCard = service.revealCard.getMockImplementation()!;
    service.getCards.mockRejectedValueOnce(new ServiceError('network', 'DockBrain couldn’t be reached.')).mockImplementation(getCards);
    service.revealCard.mockRejectedValueOnce(new ServiceError('network', 'That answer couldn’t be loaded.')).mockImplementation(revealCard);
    const { user } = renderApp({}, service);
    await openDocument(user, /Memory cards/);

    expect(await screen.findByText('Memory cards aren’t available')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Try again/ }));
    await screen.findByText('Card 1 of 5');
    await user.click(screen.getByRole('button', { name: /Show answer/ }));
    expect(await screen.findByText('That answer couldn’t be loaded.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Know it/ })).not.toBeInTheDocument(); // nothing was seen to mark
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('4.6 billion', { selector: '.memory-card__answer' })).toBeInTheDocument();
  });

  it('shows a model-written card as a question, keeping it on the back, even if the answer is reworded', async () => {
    const service = liveService({ cards: 'available' });
    service.getCards.mockResolvedValue({
      id: 'cs_1', title: 'Guide', notice: null, demo: false,
      cards: [{ id: 'c1', kind: 'question', prompt: 'Why does Mars look red?' }, { id: 'c2', kind: 'question', prompt: 'How many moons does Mars have?' }],
    });
    service.revealCard.mockResolvedValue({
      cardId: 'c1', answer: 'Rust on its surface', quote: 'Iron oxide on its surface gives it a reddish appearance.',
      citation: { index: 1, excerpt: 'Iron oxide on its surface gives it a reddish appearance.' },
    });
    const { user } = renderApp({}, service);
    await openDocument(user, /Memory cards/);
    await screen.findByText('Card 1 of 2');
    expect(document.querySelector('.memory-card__eyebrow')!.textContent).toBe('Question');
    await user.click(screen.getByRole('button', { name: /Show answer/ }));
    await screen.findByText('Rust on its surface', { selector: '.memory-card__answer' });
    expect(prompt()).toBe('Why does Mars look red?');
    expect(document.querySelector('.memory-card__quote blockquote')!.textContent).toBe('Iron oxide on its surface gives it a reddish appearance.');
  });

  it('labels nothing as a sample when the server made the cards from the document', async () => {
    const service = liveService({ cards: 'available' });
    const getCards = service.getCards.getMockImplementation()!;
    service.getCards.mockImplementation(async (id, options) => ({ ...(await getCards(id, options)), demo: false }));
    await openCards({}, service);
    expect(screen.queryByText('Sample content')).not.toBeInTheDocument();
    expect(screen.queryByText('Sample card')).not.toBeInTheDocument();
  });

  it.each([
    { label: 'unavailable', features: { cards: 'unavailable' } as const },
    { label: 'not listed (an older server)', features: { cards: undefined } },
  ])('is not offered when the server lists cards as $label', async ({ features }) => {
    const service = liveService(features);
    const { user } = renderApp({}, service);
    const choice = await screen.findByRole('button', { name: /Memory cards/ });
    await waitFor(() => expect(choice).toBeDisabled());
    await openDocument(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    expect(screen.queryByRole('tab', { name: 'Cards' })).not.toBeInTheDocument();
    expect(service.getCards).not.toHaveBeenCalled();
  });
});

describe('codebase overview', () => {
  const codeFile = (path: string, size: number) => {
    const file = new File([new Uint8Array(size)], path.split('/').pop()!);
    Object.defineProperty(file, 'webkitRelativePath', { value: path });
    return file;
  };

  it('summarises the real folder, then pages through the four demo questions', async () => {
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: /Understand a codebase/ }));
    // jsdom has no folder picker, so the app offers the multi-file fallback.
    expect(screen.getByRole('button', { name: 'Choose files' })).toBeInTheDocument();
    await user.upload(screen.getByTestId('files-input'), [
      codeFile('shop/app.py', 3000),
      codeFile('shop/web/index.ts', 1000),
      codeFile('shop/node_modules/lib/index.js', 500),
    ]);
    expect(screen.getByText('shop')).toBeInTheDocument();
    expect(screen.getByText(/2 files · 3.9 KB/)).toBeInTheDocument();
    expect(screen.getByText(/Left out 1 item in dependency or build folders/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Explore codebase/ }));
    expect(await screen.findByRole('heading', { name: 'What is this codebase about?' })).toBeInTheDocument();
    expect(screen.getByText(/“shop” wasn’t read or analysed/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'What makes it distinctive?' })).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: /Four questions/ })).getAllByRole('tab')).toHaveLength(4);

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('heading', { name: 'Why was it created?' })).toBeInTheDocument();
    screen.getByRole('tab', { name: /Why it exists/ }).focus();
    await user.keyboard('{End}');
    expect(screen.getByRole('heading', { name: 'How does it solve that problem?' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('heading', { name: 'What problem does it solve?' })).toBeInTheDocument();
  });

  it('ignores a folder drop that finishes after the person has opened a document instead', async () => {
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: /Understand a codebase/ }));
    const finishDrop = startSlowFolderDrop('late.py');
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await openDocument(user, /Learn from a document/, pdf('Current.pdf'));
    await screen.findByRole('heading', { name: 'The Solar System' });

    await act(async () => finishDrop());
    expect(screen.getByRole('heading', { level: 1, name: 'Current.pdf' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'The Solar System' })).toBeInTheDocument();
  });

  it('ignores a folder drop from an earlier visit to the folder picker', async () => {
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: /Understand a codebase/ }));
    const finishDrop = startSlowFolderDrop('old.py');
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: /Understand a codebase/ }));
    await user.upload(screen.getByTestId('files-input'), [codeFile('shop/app.py', 3000)]);

    await act(async () => finishDrop(new File([new Uint8Array(100)], 'old.py')));
    expect(screen.getByText('shop')).toBeInTheDocument();
    expect(screen.queryByText(/100 B/)).not.toBeInTheDocument();
  });

  it('keeps the newer of two folder drops when they finish out of order', async () => {
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: /Understand a codebase/ }));
    const finishFirst = startSlowFolderDrop('first.py');
    const finishSecond = startSlowFolderDrop('second.py');

    await act(async () => finishSecond(new File([new Uint8Array(2048)], 'second.py')));
    expect(screen.getByText(/1 file · 2 KB/)).toBeInTheDocument();
    await act(async () => finishFirst(new File([new Uint8Array(100)], 'first.py')));
    expect(screen.getByText(/1 file · 2 KB/)).toBeInTheDocument();
    expect(screen.queryByText(/100 B/)).not.toBeInTheDocument();
    expect(screen.queryByText('Reading folder…')).not.toBeInTheDocument();
  });

  it('labels a sample overview in a live session without saying the folder went unread', async () => {
    const { user } = renderApp({}, liveService({ codebase: 'demo' }));
    await user.click(screen.getByRole('button', { name: /Understand a codebase/ }));
    await user.upload(screen.getByTestId('files-input'), [codeFile('shop/app.py', 3000)]);
    await user.click(screen.getByRole('button', { name: /Explore codebase/ }));
    await screen.findByRole('heading', { name: 'What is this codebase about?' });

    expect(screen.getByText('Sample overview')).toBeVisible();
    expect(screen.getByText(/not an analysis of “shop”/)).toBeInTheDocument();
    expect(screen.queryByText(/wasn’t read/)).not.toBeInTheDocument();
    expect(screen.queryByText(/not analysed \(demo\)/)).not.toBeInTheDocument();
  });
});

describe('notes from a model', () => {
  it('waits to request notes until Notes or Ask is opened, since a model can take a while', async () => {
    const service = liveService({ notes: 'available', cards: 'available' });
    const { user } = renderApp({}, service);
    await openDocument(user, /Memory cards/);
    await screen.findByText('Card 1 of 5');
    expect(service.getNotes).not.toHaveBeenCalled();
    await user.click(screen.getByRole('tab', { name: 'Ask' }));
    await waitFor(() => expect(service.getNotes).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('tab', { name: 'Notes' }));
    expect(service.getNotes).toHaveBeenCalledTimes(1);
  });

  it('says so when the notes had to be built without the model', async () => {
    const service = liveService({ notes: 'available' });
    const getNotes = service.getNotes.getMockImplementation()!;
    const notice = 'These notes were built directly from the document, because the local model couldn’t write them.';
    service.getNotes.mockImplementation(async (id, options) => ({ ...(await getNotes(id, options)), demo: false, notice }));
    const { user } = renderApp({}, service);
    await openDocument(user);
    expect(await screen.findByText(notice)).toBeVisible();
  });
});

describe('partly connected servers', () => {
  it('labels sample notes in a live session without saying the document went unread', async () => {
    const { user } = renderApp({}, liveService({ notes: 'demo' }));
    await openDocument(user);
    await screen.findByRole('heading', { name: 'The Solar System' });

    expect(screen.getByText('Sample content')).toBeVisible();
    expect(screen.getByText(/These notes are a built-in sample .* not about “Fruit-Guide.pdf”/)).toBeInTheDocument();
    expect(screen.queryByText(/wasn’t read/)).not.toBeInTheDocument();
    expect(screen.queryByText(/not analysed \(demo\)/)).not.toBeInTheDocument();
  });

  it('labels a sample quiz in a live session', async () => {
    const { user } = renderApp({}, liveService({ quiz: 'demo' }));
    await openDocument(user, /Quiz yourself/);
    await screen.findByText('Question 1 of 5');
    expect(screen.getByText('Sample content')).toBeVisible();
    expect(screen.getByText(/This quiz is a built-in sample .* not about “Fruit-Guide.pdf”/)).toBeInTheDocument();
  });

  it('labels the Ask view when a live server answers with samples', async () => {
    const { user } = renderApp({}, liveService({ notes: 'unavailable', ask: 'demo' }));
    await openDocument(user);
    await screen.findByRole('heading', { level: 1, name: 'Fruit-Guide.pdf' });
    expect(screen.getByText('Sample content')).toBeVisible();
    expect(screen.getByText(/Answers here are built-in samples .* not about “Fruit-Guide.pdf”/)).toBeInTheDocument();
  });

  it('shows no sample label for live results', async () => {
    const service = liveService({ notes: 'available' });
    const sampleNotes = service.getNotes.getMockImplementation()!;
    service.getNotes.mockImplementation(async (id, options) => ({ ...(await sampleNotes(id, options)), demo: false }));
    const { user } = renderApp({}, service);
    await openDocument(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    expect(screen.queryByText('Sample content')).not.toBeInTheDocument();
  });

  it('offers only what an ask-only server supports, and never requests the rest', async () => {
    const service = liveService({ notes: 'unavailable', quiz: 'unavailable', cards: 'unavailable', codebase: 'unavailable' });
    const { user } = renderApp({}, service);

    const quizChoice = await screen.findByRole('button', { name: /Quiz yourself/ });
    await waitFor(() => expect(quizChoice).toBeDisabled());
    expect(quizChoice).toHaveAccessibleName(/isn’t available on this DockBrain server/);
    expect(screen.getByRole('button', { name: /Understand a codebase/ })).toBeDisabled();

    await openDocument(user);
    expect(await screen.findByRole('heading', { level: 1, name: 'Fruit-Guide.pdf' })).toBeInTheDocument();
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Ask']);
    expect(screen.getByRole('tab', { name: 'Ask' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(service.getNotes).not.toHaveBeenCalled();
    expect(service.getQuiz).not.toHaveBeenCalled();
  });

  it.each([
    { ask: 'available', quiz: 'unavailable', tabs: ['Notes', 'Ask'], links: ['Ask a question'] },
    { ask: 'unavailable', quiz: 'available', tabs: ['Notes', 'Quiz'], links: ['Take the quiz'] },
    { ask: 'unavailable', quiz: 'unavailable', tabs: ['Notes'], links: [] },
  ] as const)('links from the notes only to offered views (ask $ask, quiz $quiz)', async ({ ask, quiz, tabs, links }) => {
    const { user } = renderApp({}, liveService({ notes: 'available', ask, quiz, cards: 'unavailable' }));
    await openDocument(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(tabs);
    const shown = ['Ask a question', 'Take the quiz'].filter((name) => screen.queryByRole('button', { name }));
    expect(shown).toEqual(links);
    expect(screen.queryByText('Ready to go further?') !== null).toBe(links.length > 0);
  });

  it('runs a quiz on a quiz-only server without pointing to notes it lacks', async () => {
    const service = liveService({ notes: 'unavailable', ask: 'unavailable', quiz: 'available', cards: 'unavailable', codebase: 'unavailable' });
    const sampleQuiz = service.getQuiz.getMockImplementation()!;
    service.getQuiz.mockImplementation(async (id, options) => ({ ...(await sampleQuiz(id, { ...options, count: 1 })), demo: false }));
    const { user } = renderApp({}, service);
    await waitFor(() => expect(screen.getByRole('button', { name: /Learn from a document/ })).toBeDisabled());

    await openDocument(user, /Quiz yourself/);
    expect(await screen.findByText('Question 1 of 1')).toBeInTheDocument();
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Quiz']);
    await user.click(screen.getByLabelText(/4.6 billion years ago/));
    await user.click(screen.getByRole('button', { name: 'Check answer' }));
    await user.click(screen.getByRole('button', { name: /See results/ }));
    expect(await screen.findByRole('button', { name: /Retry quiz/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Review the notes/ })).not.toBeInTheDocument();
    expect(service.getNotes).not.toHaveBeenCalled();
  });
});

describe('RobotMascot', () => {
  it('falls back to the SVG robot when WebGL is unavailable, hidden from assistive technology', () => {
    const { container } = render(<RobotMascot pose="greet" />);
    const robot = container.querySelector('.robot')!;
    expect(robot).toHaveAttribute('data-renderer', 'svg');
    expect(robot).toHaveAttribute('aria-hidden', 'true');
    expect(robot.querySelector('svg')).toHaveAttribute('data-pose', 'greet');
  });

  it('does not animate the SVG robot when reduced motion is preferred', () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({ ...original(query), matches: query.includes('reduce') })) as typeof window.matchMedia;
    try {
      const { container } = render(<RobotMascot pose="idle" />);
      expect(container.querySelector('svg')).toHaveAttribute('data-animated', 'false');
    } finally {
      window.matchMedia = original;
    }
  });
});

describe('focus management', () => {
  it('moves focus to each new screen’s heading after navigation', async () => {
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: /Learn from a document/ }));
    expect(screen.getByRole('heading', { level: 1, name: 'Put your document here' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByRole('heading', { level: 1, name: 'What would you like to explore today?' })).toHaveFocus();
  });
});

describe('demo mode explanation', () => {
  it('opens from the top bar and closes with Escape', async () => {
    const { user } = renderApp();
    const summary = screen.getByText('Demo mode', { selector: 'summary' });
    await user.click(summary);
    expect(screen.getByText(/Nothing is analysed in demo mode/)).toBeVisible();
    await user.keyboard('{Escape}');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    expect(summary).toHaveFocus();
  });
});

describe('stage layout', () => {
  // Titles are drawn in the stage band's colours; outside the band they would be white on a light page.
  const titleOnBand = (name: string) => expect(screen.getByRole('heading', { level: 1, name }).closest('.band')).not.toBeNull();
  const shell = () => document.querySelector('.app');

  it('puts each document screen’s title on the stage band', async () => {
    const { user } = renderApp();
    titleOnBand('What would you like to explore today?');

    await user.click(screen.getByRole('button', { name: /Learn from a document/ }));
    titleOnBand('Put your document here');
    await openDocumentFromSelect(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    titleOnBand('Fruit-Guide.pdf');
  });

  it('puts the codebase screen’s title on the stage band too', async () => {
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: /Understand a codebase/ }));
    titleOnBand('Put your project folder here');
    await user.upload(screen.getByTestId('files-input'), [new File(['print(1)'], 'app.py')]);
    await user.click(screen.getByRole('button', { name: /Explore codebase/ }));
    await screen.findByRole('heading', { name: 'What is this codebase about?' });
    expect(screen.getByRole('heading', { level: 1 }).closest('.band')).not.toBeNull();
  });

  it('tells the stylesheet which screen is showing, so each can size its page', async () => {
    const { user } = renderApp();
    expect(shell()).toHaveAttribute('data-screen', 'welcome');
    await user.click(screen.getByRole('button', { name: /Learn from a document/ }));
    expect(shell()).toHaveAttribute('data-screen', 'select');
    await openDocumentFromSelect(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    expect(shell()).toHaveAttribute('data-screen', 'workspace');
  });

  it('attaches the confirmation dialog to the page body, outside the band it was opened from', async () => {
    const { user } = renderApp();
    await openDocument(user);
    await user.click(screen.getByRole('tab', { name: 'Ask' }));
    await user.click(await screen.findByRole('button', { name: 'Which planet is the largest?' }));
    await screen.findByRole('article', { name: 'Answer, from the document' });

    await user.click(screen.getByRole('button', { name: 'Start over' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog.parentElement).toBe(document.body);
    expect(dialog.closest('.band')).toBeNull();
  });
});

describe('theme switch', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('is in the top bar on every screen', async () => {
    const { user } = renderApp();
    expect(screen.getByRole('banner')).toContainElement(screen.getByRole('button', { name: 'Switch to dark theme' }));

    await user.click(screen.getByRole('button', { name: /Learn from a document/ }));
    expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument();
    await openDocumentFromSelect(user);
    await screen.findByRole('heading', { name: 'The Solar System' });
    expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument();
  });

  it('keeps the chosen theme as the app moves between screens', async () => {
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: 'Switch to dark theme' }));
    await openDocument(user);
    await screen.findByRole('heading', { name: 'The Solar System' });

    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeInTheDocument();
  });
});

async function openDocumentFromSelect(user: ReturnType<typeof renderApp>['user']) {
  await user.upload(screen.getByTestId('document-input'), pdf());
  await user.click(screen.getByRole('button', { name: /Open document/ }));
}
