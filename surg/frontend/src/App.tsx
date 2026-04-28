import { useState, useEffect } from 'react';
import { useSocket } from './useSocket';
import Header from './components/Header';
import FlagTable from './components/FlagTable';
import EventLog from './components/EventLog';
import AuditHistory from './components/AuditHistory';
import ShutdownToast from './components/ShutdownToast';

type PanelId = 'flags' | 'events' | 'audit';
const ALL_PANELS: PanelId[] = ['flags', 'events', 'audit'];

export default function App() {
  const [state, actions] = useSocket();
  const [visible, setVisible] = useState<Set<PanelId>>(new Set(ALL_PANELS));
  const [isDark, setIsDark] = useState(() => localStorage.getItem('theme') !== 'light');
  const markSrc = isDark ? '/surg-logo-mark-dark-mode.png' : '/surg-logo-mark-light-mode.png';

  useEffect(() => {
    document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
  }, [isDark]);

  function closePanel(id: PanelId) {
    setVisible(prev => { const s = new Set(prev); s.delete(id); return s; });
    if (id === 'events') actions.setEventLogActive(false);
  }
  function resetLayout() {
    setVisible(new Set(ALL_PANELS));
    actions.setEventLogActive(true);
  }

  const showFlags = visible.has('flags');
  const showEvents = visible.has('events');
  const showAudit = visible.has('audit');
  const hasBottom = showEvents || showAudit;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-(--c-base)">
      <Header
        grusStatus={state.grusStatus}
        connected={state.connected}
        visiblePanels={visible}
        onResetLayout={resetLayout}
        isDark={isDark}
        onToggleTheme={() => setIsDark(d => !d)}
      />

      <div className="flex-1 overflow-hidden flex flex-col p-3 gap-3 min-h-0">
        {visible.size === 0 ? (
          <div className="flex flex-col items-center justify-center flex-1 text-(--c-t2) gap-3">
            <img src={markSrc} alt="Surg" className="w-24 opacity-30" />
            <p className="text-sm">All panels closed.</p>
            <button
              onClick={resetLayout}
              className="px-4 py-2 text-sm rounded bg-(--c-muted) hover:bg-(--c-hover) text-(--c-t1) transition-colors"
            >
              Reset Layout
            </button>
          </div>
        ) : (
          <>
            {showFlags && (
              <div className={hasBottom ? 'h-[45%] min-h-0' : 'flex-1 min-h-0'}>
                <FlagTable
                  flags={state.flags}
                  actions={actions}
                  onClose={() => closePanel('flags')}
                />
              </div>
            )}

            {hasBottom && (
              <div className="flex gap-3 min-h-0 flex-1">
                {showEvents && (
                  <div className={showAudit ? 'flex-1 min-w-0 min-h-0' : 'flex-1 min-h-0'}>
                    <EventLog
                      events={state.eventLog}
                      actions={actions}
                      onClose={() => closePanel('events')}
                    />
                  </div>
                )}
                {showAudit && (
                  <div className={showEvents ? 'flex-1 min-w-0 min-h-0' : 'flex-1 min-h-0'}>
                    <AuditHistory
                      liveRecords={state.auditRecords}
                      actions={actions}
                      onClose={() => closePanel('audit')}
                    />
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <ShutdownToast
        secondsRemaining={state.shutdownSeconds}
        onKeepAlive={actions.keepAlive}
      />
    </div>
  );
}
