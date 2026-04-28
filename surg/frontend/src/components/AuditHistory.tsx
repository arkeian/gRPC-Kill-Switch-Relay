import { useState, useEffect, useCallback } from 'react';
import type { AuditRecord } from '../types';
import type { SocketActions } from '../useSocket';

interface Props {
  liveRecords: AuditRecord[];
  actions: SocketActions;
  onClose: () => void;
}

const PAGE_SIZE = 50;

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

function BoolBadge({ val }: { val: boolean }) {
  return (
    <span className={`px-1.5 py-0.5 text-[10px] rounded font-mono ${val ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'bg-[#ef4444]/15 text-[#ef4444]'}`}>
      {val ? 'ON' : 'OFF'}
    </span>
  );
}

export default function AuditHistory({ liveRecords, actions, onClose }: Props) {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const rows = await actions.getAuditHistory({ limit: PAGE_SIZE + 1, offset: p * PAGE_SIZE });
      setRecords(rows.slice(0, PAGE_SIZE));
      setHasMore(rows.length > PAGE_SIZE);
    } finally {
      setLoading(false);
    }
  }, [actions]);

  useEffect(() => { load(0); }, [load]);

  useEffect(() => {
    if (page !== 0) return;
    const interval = window.setInterval(() => {
      if (!loading) {
        load(0);
      }
    }, 15000);
    return () => window.clearInterval(interval);
  }, [load, page, loading]);

  useEffect(() => {
    if (page === 0 && liveRecords.length > 0) {
      setRecords(prev => {
        const merged = [...liveRecords.slice(0, 10), ...prev];
        const seen = new Set<string>();
        return merged.filter(r => {
          const key = `${r.flag_name}-${r.changed_at}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        }).slice(0, PAGE_SIZE * 2);
      });
    }
  }, [liveRecords, page]);

  function changePage(p: number) {
    setPage(p);
    load(p);
  }

  return (
    <div className="flex flex-col h-full bg-(--c-panel) border border-(--c-border) rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-(--c-border)">
        <span className="text-xs font-semibold text-(--c-t1) uppercase tracking-wider">Audit History</span>
        <div className="flex items-center gap-2">
          <button onClick={() => load(page)} className="text-(--c-t2) hover:text-(--c-t1) text-xs">Refresh</button>
          <button onClick={onClose} className="text-(--c-t2) hover:text-(--c-t1) text-sm leading-none px-1">✕</button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {loading && records.length === 0 && (
          <div className="flex items-center justify-center h-full text-(--c-t2) text-sm">Loading…</div>
        )}
        {!loading && records.length === 0 && (
          <div className="flex items-center justify-center h-full text-(--c-t2) text-sm">No audit records yet.</div>
        )}
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-(--c-panel)">
            <tr className="border-b border-(--c-border) text-(--c-t2)">
              <th className="text-left px-4 py-2 font-medium">Time</th>
              <th className="text-left px-4 py-2 font-medium">Flag</th>
              <th className="text-left px-4 py-2 font-medium">Change</th>
              <th className="text-left px-4 py-2 font-medium">By</th>
              <th className="text-left px-4 py-2 font-medium">Reason</th>
              <th className="text-left px-4 py-2 font-medium">Policy</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r, i) => (
              <tr key={i} className="border-b border-(--c-row-border) hover:bg-(--c-row)">
                <td className="px-4 py-2 text-(--c-t2) whitespace-nowrap font-mono">{fmtTime(r.changed_at)}</td>
                <td className="px-4 py-2 font-mono text-(--c-t1)">{r.flag_name}</td>
                <td className="px-4 py-2 whitespace-nowrap">
                  <BoolBadge val={r.old_value} />
                  <span className="mx-1 text-(--c-t2)">→</span>
                  <BoolBadge val={r.new_value} />
                </td>
                <td className="px-4 py-2 text-(--c-t3)">{r.changed_by}</td>
                <td className="px-4 py-2 text-(--c-t3) max-w-xs truncate">{r.reason || '-'}</td>
                <td className="px-4 py-2">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] ${r.policy_result === 'approved' ? 'bg-[#22c55e]/15 text-[#22c55e]' : 'bg-[#ef4444]/15 text-[#ef4444]'}`}>
                    {r.policy_result}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between px-4 py-2 border-t border-(--c-border) text-xs text-(--c-t2)">
        <button
          onClick={() => changePage(Math.max(0, page - 1))}
          disabled={page === 0 || loading}
          className="px-2 py-1 rounded bg-(--c-muted) disabled:opacity-[0.38] hover:bg-(--c-hover)"
        >
          ← Prev
        </button>
        <span>Page {page + 1}{!hasMore && page === 0 ? ` · ${records.length} records` : ''}</span>
        <button
          onClick={() => changePage(page + 1)}
          disabled={!hasMore || loading}
          className="px-2 py-1 rounded bg-(--c-muted) disabled:opacity-[0.38] hover:bg-(--c-hover)"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
