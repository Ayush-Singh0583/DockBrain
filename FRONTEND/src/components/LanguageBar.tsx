import type { LanguageShare } from '../lib/folderSelection';

// The accent, then paler tints of it, so the bar reads in both themes.
const SHADES = [
  'var(--accent)',
  'color-mix(in srgb, var(--accent) 65%, var(--surface))',
  'color-mix(in srgb, var(--accent) 40%, var(--surface))',
  'color-mix(in srgb, var(--accent) 22%, var(--surface))',
];

/** Share of recognised source bytes per language, from file names and sizes only. */
export function LanguageBar({ languages, limit = 4 }: { languages: LanguageShare[]; limit?: number }) {
  const top = languages.slice(0, limit);
  const otherShare = languages.slice(limit).reduce((sum, l) => sum + l.share, 0);
  const rows = otherShare > 0.005 ? [...top, { name: 'Other', share: otherShare }] : top;
  const percent = (share: number) => (share >= 0.995 ? '100%' : share < 0.01 ? '<1%' : `${Math.round(share * 100)}%`);

  return (
    <div className="languages">
      <div className="languages__bar" aria-hidden="true">
        {rows.map((lang, i) => (
          <span
            key={lang.name}
            style={{ flexGrow: Math.max(lang.share, 0.01), background: SHADES[i] ?? 'var(--surface-3)' }}
          />
        ))}
      </div>
      <ul className="languages__legend" aria-label="Languages by size">
        {rows.map((lang, i) => (
          <li key={lang.name}>
            <span className="languages__swatch" style={{ background: SHADES[i] ?? 'var(--surface-3)' }} aria-hidden="true" />
            {lang.name} <span className="muted">{percent(lang.share)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
