import { useState, useEffect } from 'react';
import type { FlagUpdate } from '../types';
import type { SocketActions } from '../useSocket';

interface Props {
  events: FlagUpdate[];
  actions: SocketActions;
  onClose: () => void;
}

const PAGE_SIZE = 50;

function RefreshIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="1 4 1 10 7 10"/>
      <polyline points="23 20 23 14 17 14"/>
      <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10M23 14l-4.64 4.36A9 9 0 0 1 3.51 15"/>
    </svg>
  );
}

const CHANGE_COLOR: Record<string, string> = {
  ENABLED: '#22c55e',
  DISABLED: '#ef4444',
  CREATED: '#6366f1',
  UPDATED: '#64748b',
  DELETED: '#ef4444',
};

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

function BoolBadge({ val }: { val: boolean }) {
  return (
    <span className={`px-1.5 py-0.5 text-[10px] rounded font-mono ${val ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'bg-[#ef4444]/15 text-[#ef4444]'}`}>
      {val ? 'ON' : 'OFF'}
    </span>
  );
}

export default function EventLog({ events, actions, onClose }: Props) {
  const [page, setPage] = useState(0);

  useEffect(() => {
    const maxPage = Math.max(0, Math.ceil(events.length / PAGE_SIZE) - 1);
    if (page > maxPage) setPage(maxPage);
  }, [events.length, page]);

  const totalPages = Math.max(1, Math.ceil(events.length / PAGE_SIZE));
  const slice = events.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="flex flex-col h-full bg-(--c-panel) border border-(--c-border) rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-(--c-border)">
        <span className="text-xs font-semibold text-(--c-t1) uppercase tracking-wider">Live Flag Broadcast</span>
        <div className="flex items-center gap-2">
          <button onClick={() => actions.refreshFlags()} title="Refresh" className="text-(--c-t2) hover:text-(--c-t1) flex items-center"><RefreshIcon /></button>
          <button onClick={onClose} className="text-(--c-t2) hover:text-(--c-t1) text-sm leading-none px-1">✕</button>
        </div>
      </div>

      <div className="flex-1 overflow-auto font-mono text-xs">
        {slice.length === 0 && (
          <div className="flex items-center justify-center h-full text-(--c-t2)">
            Waiting for flag changes…
          </div>
        )}
        {slice.map((ev, i) => (
          <div key={`${ev.timestamp}-${i}`} className="flex items-start gap-3 px-4 py-2 border-b border-(--c-row-border) hover:bg-(--c-row)">
            <span className="text-(--c-t2) shrink-0 pt-0.5">{fmtTime(ev.timestamp)}</span>
            <span
              className="shrink-0 pt-0.5 font-semibold text-[10px]"
              style={{ color: CHANGE_COLOR[ev.change_type] ?? '#94a3b8' }}
            >
              {ev.change_type}
            </span>
            <div className="flex-1 min-w-0">
              <span className="text-(--c-t1) font-semibold">{ev.name}</span>
              {ev.change_type !== 'DELETED' && (
                <span className="ml-2 text-(--c-t2)">
                  <BoolBadge val={ev.old_value} /> → <BoolBadge val={ev.enabled} />
                </span>
              )}
            </div>
            <span className="text-(--c-t2) shrink-0">{ev.changed_by}</span>
          </div>
        ))}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-2 border-t border-(--c-border) text-xs text-(--c-t2)">
          <button
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-2 py-1 rounded bg-(--c-muted) disabled:opacity-[0.38] hover:bg-(--c-hover)"
          >
            ← Prev
          </button>
          <span>Page {page + 1} / {totalPages} ({events.length} events)</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="px-2 py-1 rounded bg-(--c-muted) disabled:opacity-[0.38] hover:bg-(--c-hover)"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
