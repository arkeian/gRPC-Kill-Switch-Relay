import type { GrusStatus } from '../types';

interface Props {
  grusStatus: GrusStatus;
  connected: boolean;
  visiblePanels: Set<string>;
  onResetLayout: () => void;
  isDark: boolean;
  onToggleTheme: () => void;
}

const SVC_LABELS: [keyof GrusStatus, string][] = [
  ['flag_store', 'FlagStore'],
  ['policy_evaluator', 'Policy'],
  ['broadcaster', 'Broadcaster'],
  ['audit_logger', 'AuditLogger'],
];

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

export default function Header({ grusStatus, connected, visiblePanels, onResetLayout, isDark, onToggleTheme }: Props) {
  const allVisible = visiblePanels.size === 3;
  const logoSrc = isDark ? '/surg-combination-mark-dark-mode.png' : '/surg-combination-mark-light-mode.png';

  return (
    <header className="flex items-center justify-between px-5 py-3 border-b border-(--c-border) bg-(--c-panel) shrink-0">
      <div className="flex items-center gap-3">
        <img src={logoSrc} alt="Surg" className="h-[42px] object-contain" />
      </div>

      <div className="flex items-center gap-4">
        {SVC_LABELS.map(([key, label]) => (
          <div key={key} className="flex items-center gap-1.5">
            <span
              className="w-2 h-2 rounded-full"
              style={{ background: grusStatus[key] ? '#22c55e' : '#ef4444' }}
            />
            <span className="text-(--c-t2) text-xs">{label}</span>
          </div>
        ))}

        <div className="w-px h-4 bg-(--c-border)" />

        <div className="flex items-center gap-1.5">
          <span
            className="w-2 h-2 rounded-full"
            style={{ background: connected ? '#6366f1' : '#64748b' }}
          />
          <span className="text-(--c-t2) text-xs">{connected ? 'Live' : 'Disconnected'}</span>
        </div>

        <div className="w-px h-4 bg-(--c-border)" />

        <button
          onClick={onToggleTheme}
          title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          className="w-7 h-7 flex items-center justify-center rounded text-(--c-t2) hover:text-(--c-t1) hover:bg-(--c-muted) transition-colors"
        >
          {isDark ? <SunIcon /> : <MoonIcon />}
        </button>

        {!allVisible && (
          <button
            onClick={onResetLayout}
            className="px-3 py-1 text-xs rounded bg-(--c-muted) hover:bg-(--c-hover) text-(--c-t1) transition-colors"
          >
            Reset Layout
          </button>
        )}
      </div>
    </header>
  );
}
