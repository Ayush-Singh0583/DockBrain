import { useEffect, useState } from 'react';
import { ArrowRight, BookOpen, FolderCode, Layers, ListChecks } from 'lucide-react';
import { RobotMascot } from '../components/robot/RobotMascot';
import { usePrefersReducedMotion } from '../components/robot/capabilities';
import type { RobotFacing, RobotPose } from '../components/robot/types';
import { SpeechBubble } from '../components/ui';
import { useScreenHeading, type ScreenProps } from '../app/navigation';
import { offers, type Activity } from '../services/types';
import './welcome.css';

const CHOICES: { activity: Activity; title: string; description: string; icon: typeof BookOpen; facing: RobotFacing }[] = [
  {
    activity: 'learn',
    title: 'Learn from a document',
    description: 'Key notes, then questions answered with cited passages.',
    icon: BookOpen,
    facing: 'left',
  },
  {
    activity: 'quiz',
    title: 'Quiz yourself',
    description: 'Questions one at a time, each with an explanation.',
    icon: ListChecks,
    facing: 'front',
  },
  {
    activity: 'cards',
    title: 'Memory cards',
    description: 'Flip cards from your document and mark what to review.',
    icon: Layers,
    facing: 'front',
  },
  {
    activity: 'codebase',
    title: 'Understand a codebase',
    description: 'A guided overview of a project folder: what, why and how.',
    icon: FolderCode,
    facing: 'right',
  },
];

export function WelcomeScreen({ dispatch, capabilities }: ScreenProps) {
  const heading = useScreenHeading<HTMLHeadingElement>();
  const reducedMotion = usePrefersReducedMotion();
  const [greeting, setGreeting] = useState(true);
  const [focus, setFocus] = useState<RobotFacing | null>(null);

  useEffect(() => {
    if (reducedMotion) return; // keep a still, friendly wave rather than an abrupt change
    const timer = setTimeout(() => setGreeting(false), 2600);
    return () => clearTimeout(timer);
  }, [reducedMotion]);

  const pose: RobotPose = focus && focus !== 'front' ? 'point' : greeting ? 'greet' : 'idle';
  const demo = capabilities?.mode !== 'live';
  const offered: Record<Activity, boolean> = {
    learn: offers(capabilities, 'notes') || offers(capabilities, 'ask'),
    quiz: offers(capabilities, 'quiz'),
    cards: offers(capabilities, 'cards'),
    codebase: offers(capabilities, 'codebase'),
  };

  return (
    <section className="welcome" aria-labelledby="welcome-title">
      {/* The stage: the robot greets you on the band, and the activities rise over its edge,
          all in view as soon as the page opens. */}
      <div className="band">
        <div className="band__inner welcome__hero">
          <RobotMascot pose={pose} facing={focus ?? 'front'} size="xl" className="welcome__robot" />
          <SpeechBubble tail="top" tailOffset="50%" className="welcome__bubble">
            <p className="bubble__text">Hi, I’m DockBrain.</p>
          </SpeechBubble>
          <h1 id="welcome-title" className="welcome__title" ref={heading} tabIndex={-1}>
            What would you like to <span className="welcome__hi">explore</span> today?
          </h1>
          <p className="welcome__lede">
            Pick an activity. I’ll read what you give me and show where every answer comes from.
          </p>
        </div>
      </div>

      <div className="stage">
        <ul className="choices" onMouseLeave={() => setFocus(null)}>
          {CHOICES.map(({ activity, title, description, icon: Icon, facing }) => (
            <li key={activity}>
              <button
                type="button"
                className="choice"
                disabled={!offered[activity]}
                onClick={() => dispatch({ type: 'chooseActivity', activity })}
                onMouseEnter={() => offered[activity] && setFocus(facing)}
                onFocus={() => setFocus(facing)}
                onBlur={() => setFocus(null)}
              >
                <span className="choice__icon" aria-hidden="true">
                  <Icon />
                </span>
                <span className="choice__text">
                  <span className="choice__title">{title}</span>
                  <span className="choice__description">
                    {offered[activity] ? description : 'This isn’t available on this DockBrain server yet.'}
                  </span>
                </span>
                {offered[activity] && <ArrowRight className="choice__arrow" aria-hidden="true" />}
              </button>
            </li>
          ))}
        </ul>

        {demo && (
          <p className="welcome__note">
            Demo mode: you can choose real files, but notes, answers, quizzes, cards and overviews are built-in samples
            until DockBrain’s backend is connected.
          </p>
        )}
      </div>
    </section>
  );
}
