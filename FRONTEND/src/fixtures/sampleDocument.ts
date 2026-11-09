/**
 * Demo fixtures for the document flows. Everything here describes DockBrain's bundled
 * sample document (`sample.txt` at the repository root, "The Solar System"), never the
 * file the user selected. The UI labels these results as demo content.
 */
import type { Answer, AnswerOrigin, CardAnswer, CardSet, Citation, Notes, Quiz } from '../services/types';

export const SAMPLE_DOCUMENT_NAME = 'sample.txt — “The Solar System”';
export const SAMPLE_SECTION_COUNT = 5;

const SECTION = 'The Solar System';

/** The sample's five paragraphs, used as citable excerpts. */
export const sampleExcerpts: Citation[] = [
  {
    index: 1,
    section: SECTION,
    excerpt:
      'The Solar System formed about 4.6 billion years ago from the gravitational collapse of a giant molecular cloud. Most of its mass is in the Sun, and the rest is mostly in Jupiter.',
  },
  {
    index: 2,
    section: SECTION,
    excerpt:
      'There are eight planets. The four inner planets, Mercury, Venus, Earth and Mars, are terrestrial planets made of rock and metal. The four outer planets are giants: Jupiter and Saturn are gas giants, while Uranus and Neptune are ice giants.',
  },
  {
    index: 3,
    section: SECTION,
    excerpt:
      'Jupiter is the largest planet. It has a mass more than twice that of all the other planets combined. Its Great Red Spot is a storm that has lasted for at least 350 years.',
  },
  {
    index: 4,
    section: SECTION,
    excerpt:
      'Mars is called the Red Planet because iron oxide on its surface gives it a reddish appearance. It has two small moons, Phobos and Deimos. Olympus Mons on Mars is the tallest volcano in the Solar System.',
  },
  {
    index: 5,
    section: SECTION,
    excerpt:
      'Pluto was considered the ninth planet until 2006, when the International Astronomical Union reclassified it as a dwarf planet.',
  },
];

function excerpts(...indices: number[]): Citation[] {
  // Renumber so an answer's citations always read [1], [2], … like the backend's.
  return indices.map((source, i) => ({ ...sampleExcerpts[source - 1]!, index: i + 1 }));
}

export const sampleNotes: Notes = {
  title: 'The Solar System',
  summary:
    'A short overview of how the Solar System formed, how its eight planets are grouped, and notable facts about Jupiter, Mars and Pluto.',
  sections: [
    {
      id: 'formation',
      heading: 'Formation',
      points: [
        { text: 'Formed about 4.6 billion years ago from the collapse of a giant molecular cloud.', citations: [1] },
        { text: 'Most of its mass is in the Sun; most of the remainder is in Jupiter.', citations: [1] },
      ],
    },
    {
      id: 'planets',
      heading: 'The eight planets',
      points: [
        { text: 'Inner, terrestrial planets of rock and metal: Mercury, Venus, Earth and Mars.', citations: [2] },
        { text: 'Outer giants: Jupiter and Saturn are gas giants; Uranus and Neptune are ice giants.', citations: [2] },
      ],
    },
    {
      id: 'jupiter',
      heading: 'Jupiter',
      points: [
        { text: 'The largest planet, with more than twice the mass of all other planets combined.', citations: [3] },
        { text: 'Its Great Red Spot is a storm that has lasted at least 350 years.', citations: [3] },
      ],
    },
    {
      id: 'mars',
      heading: 'Mars',
      points: [
        { text: 'Called the Red Planet because iron oxide colours its surface.', citations: [4] },
        { text: 'Has two small moons, Phobos and Deimos.', citations: [4] },
        { text: 'Olympus Mons is the tallest volcano in the Solar System.', citations: [4] },
      ],
    },
    {
      id: 'pluto',
      heading: 'Pluto',
      points: [
        {
          text: 'Counted as the ninth planet until 2006, when the International Astronomical Union reclassified it as a dwarf planet.',
          citations: [5],
        },
      ],
    },
  ],
  sources: sampleExcerpts,
  suggestedQuestions: [
    'Which planet is the largest?',
    'Why is Mars called the Red Planet?',
    'Who discovered Neptune?',
    'How many moons does Mars have, and who discovered them?',
    'How far is Mars from the Sun?',
  ],
  demo: true,
};

interface CannedAnswer {
  /** Every group must have at least one word present in the question. */
  match: string[][];
  text: string;
  origin: AnswerOrigin;
  sources: number[];
}

/**
 * Wording follows the backend's conventions: cited answers use [n]; outside knowledge
 * starts "It wasn't in the information I was given, but"; a mixed answer labels the
 * outside part "The rest wasn't in the information I was given, but".
 */
const cannedAnswers: CannedAnswer[] = [
  {
    match: [['largest', 'biggest', 'big', 'large'], ['planet', 'planets']],
    text: 'Jupiter is the largest planet [1]. It has more than twice the mass of all the other planets combined [1].',
    origin: 'document',
    sources: [3],
  },
  {
    match: [['mars'], ['red', 'colour', 'color', 'reddish']],
    text: 'Mars looks red because iron oxide on its surface gives it a reddish appearance [1].',
    origin: 'document',
    sources: [4],
  },
  {
    match: [['neptune'], ['discovered', 'discover', 'found', 'discovery']],
    text: "It wasn't in the information I was given, but Neptune was first observed in 1846 by Johann Galle, using positions predicted by Urbain Le Verrier.",
    origin: 'general',
    sources: [],
  },
  {
    match: [['moons', 'moon'], ['mars']],
    text: "Mars has two small moons, Phobos and Deimos [1]. The rest wasn't in the information I was given, but both were discovered by Asaph Hall in 1877.",
    origin: 'mixed',
    sources: [4],
  },
  {
    match: [['formed', 'form', 'old', 'age', 'formation']],
    text: 'The Solar System formed about 4.6 billion years ago from the gravitational collapse of a giant molecular cloud [1].',
    origin: 'document',
    sources: [1],
  },
  {
    match: [['pluto']],
    text: 'Pluto was considered the ninth planet until 2006, when the International Astronomical Union reclassified it as a dwarf planet [1].',
    origin: 'document',
    sources: [5],
  },
  {
    match: [['volcano', 'olympus', 'tallest']],
    text: 'Olympus Mons, on Mars, is the tallest volcano in the Solar System [1].',
    origin: 'document',
    sources: [4],
  },
  {
    match: [['ice', 'gas', 'giant', 'giants']],
    text: 'Jupiter and Saturn are gas giants, while Uranus and Neptune are ice giants [1].',
    origin: 'document',
    sources: [2],
  },
];

const INSUFFICIENT_TEXT =
  "I couldn't find an answer using the words in this question. The document may use different wording.";

function words(question: string): Set<string> {
  return new Set(question.toLowerCase().match(/[a-z]+/g) ?? []);
}

/** The canned demo answer for a question, or an "insufficient evidence" reply. */
export function sampleAnswerFor(question: string, id: string): Answer {
  const asked = words(question);
  const canned = cannedAnswers.find((c) => c.match.every((group) => group.some((w) => asked.has(w))));
  if (!canned) {
    return {
      id,
      question,
      text: INSUFFICIENT_TEXT,
      origin: 'insufficient',
      citations: [],
      coverage: { searched: SAMPLE_SECTION_COUNT, total: SAMPLE_SECTION_COUNT },
      demo: true,
    };
  }
  return {
    id,
    question,
    text: canned.text,
    origin: canned.origin,
    citations: excerpts(...canned.sources),
    // The sample is small, so the backend would send it whole (6 sections or fewer).
    coverage: { searched: SAMPLE_SECTION_COUNT, total: SAMPLE_SECTION_COUNT },
    demo: true,
  };
}

export const sampleQuiz: Quiz = {
  id: 'sample-quiz',
  title: 'The Solar System',
  demo: true,
  questions: [
    {
      id: 'q1',
      prompt: 'About how long ago did the Solar System form?',
      options: [
        { id: 'a', text: '460 million years ago' },
        { id: 'b', text: '4.6 billion years ago' },
        { id: 'c', text: '13.8 billion years ago' },
        { id: 'd', text: '1.2 billion years ago' },
      ],
      correctOptionId: 'b',
      explanation: 'It formed about 4.6 billion years ago from the gravitational collapse of a giant molecular cloud.',
      citation: excerpts(1)[0],
    },
    {
      id: 'q2',
      prompt: 'Which of these planets is an ice giant?',
      options: [
        { id: 'a', text: 'Saturn' },
        { id: 'b', text: 'Jupiter' },
        { id: 'c', text: 'Neptune' },
        { id: 'd', text: 'Mars' },
      ],
      correctOptionId: 'c',
      explanation: 'Uranus and Neptune are ice giants. Jupiter and Saturn are gas giants, and Mars is a terrestrial planet.',
      citation: excerpts(2)[0],
    },
    {
      id: 'q3',
      prompt: 'Why is Mars called the Red Planet?',
      options: [
        { id: 'a', text: 'Iron oxide on its surface gives it a reddish appearance' },
        { id: 'b', text: 'Its two moons reflect red light onto it' },
        { id: 'c', text: 'A giant storm covers its surface' },
        { id: 'd', text: 'Lava from Olympus Mons glows red' },
      ],
      correctOptionId: 'a',
      explanation: 'The reddish colour comes from iron oxide on the surface of Mars.',
      citation: excerpts(4)[0],
    },
    {
      id: 'q4',
      prompt: 'What is the Great Red Spot?',
      options: [
        { id: 'a', text: 'A volcano on Mars' },
        { id: 'b', text: 'A storm on Jupiter that has lasted at least 350 years' },
        { id: 'c', text: 'A crater on Mercury' },
        { id: 'd', text: 'The shadow of Saturn’s rings' },
      ],
      correctOptionId: 'b',
      explanation: 'The Great Red Spot is a storm on Jupiter that has lasted for at least 350 years.',
      citation: excerpts(3)[0],
    },
    {
      id: 'q5',
      prompt: 'What changed for Pluto in 2006?',
      options: [
        { id: 'a', text: 'It was discovered' },
        { id: 'b', text: 'It was named the ninth planet' },
        { id: 'c', text: 'It was reclassified as a dwarf planet' },
        { id: 'd', text: 'It lost its largest moon' },
      ],
      correctOptionId: 'c',
      explanation: 'The International Astronomical Union reclassified Pluto as a dwarf planet in 2006.',
      citation: excerpts(5)[0],
    },
  ],
};

/**
 * Sample memory cards, shaped like the backend's: each answer is words from its quote,
 * and each quote a sentence of the sample's passage it cites.
 */
const cardBacks: { id: string; kind: 'definition' | 'cloze'; prompt: string; answer: string; quote: string; source: number }[] = [
  {
    id: 'c1',
    kind: 'cloze',
    prompt: 'Fill in the blank: “The Solar System formed about _____ years ago from the gravitational collapse of a giant molecular cloud.”',
    answer: '4.6 billion',
    quote: 'The Solar System formed about 4.6 billion years ago from the gravitational collapse of a giant molecular cloud.',
    source: 1,
  },
  {
    id: 'c2',
    kind: 'cloze',
    prompt: 'Fill in the blank: “The four outer planets are giants: Jupiter and Saturn are gas giants, while Uranus and _____ are ice giants.”',
    answer: 'Neptune',
    quote: 'The four outer planets are giants: Jupiter and Saturn are gas giants, while Uranus and Neptune are ice giants.',
    source: 2,
  },
  {
    id: 'c3',
    kind: 'definition',
    prompt: 'What is Jupiter?',
    answer: 'the largest planet',
    quote: 'Jupiter is the largest planet.',
    source: 3,
  },
  {
    id: 'c4',
    kind: 'cloze',
    prompt: 'Fill in the blank: “It has two small moons, Phobos and _____.”',
    answer: 'Deimos',
    quote: 'It has two small moons, Phobos and Deimos.',
    source: 4,
  },
  {
    id: 'c5',
    kind: 'cloze',
    prompt:
      'Fill in the blank: “Pluto was considered the ninth planet until _____, when the International Astronomical Union reclassified it as a dwarf planet.”',
    answer: '2006',
    quote: 'Pluto was considered the ninth planet until 2006, when the International Astronomical Union reclassified it as a dwarf planet.',
    source: 5,
  },
];

export const sampleCards: CardSet = {
  id: 'sample-cards',
  title: 'The Solar System',
  cards: cardBacks.map(({ id, kind, prompt }) => ({ id, kind, prompt })),
  notice: null,
  demo: true,
};

/** A sample card's back, or undefined for a card that isn't in the sample set. */
export function sampleCardAnswer(cardId: string): CardAnswer | undefined {
  const card = cardBacks.find((c) => c.id === cardId);
  if (!card) return undefined;
  return { cardId: card.id, answer: card.answer, quote: card.quote, citation: { ...sampleExcerpts[card.source - 1]!, index: 1 } };
}
