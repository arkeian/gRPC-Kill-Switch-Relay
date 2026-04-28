import { useState, useEffect } from 'react';
import type { Flag } from '../types';
import type { SocketActions } from '../useSocket';

interface Props {
  flags: Flag[];
  actions: SocketActions;
  onClose: () => void;
}

interface ModalState {
  mode: 'edit' | 'delete' | 'policy' | null;
  flag: Flag | null;
}

function Toggle({ enabled, onChange }: { enabled: boolean; onChange: () => void }) {
  return (
    <button
      onClick={onChange}
      className={`relative inline-flex items-center h-6 w-11 shrink-0 cursor-pointer rounded-full p-0.5 transition-colors ${enabled ? 'bg-[#22c55e]' : 'bg-(--c-muted)'}`}
    >
      <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${enabled ? 'translate-x-5' : 'translate-x-0'}`} />
    </button>
  );
}

export default function FlagTable({ flags, actions, onClose }: Props) {
  const [modal, setModal] = useState<ModalState>({ mode: null, flag: null });
  const [feedback, setFeedback] = useState<string | null>(null);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [mutexConfirm, setMutexConfirm] = useState<{ flag: Flag; other: Flag } | null>(null);

  useEffect(() => {
    if (!openMenu) return;
    const close = () => setOpenMenu(null);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [openMenu]);

  function openEdit(f: Flag) { setModal({ mode: 'edit', flag: { ...f } }); }
  function openDelete(f: Flag) { setModal({ mode: 'delete', flag: { ...f } }); }
  function openPolicy(f: Flag) { setModal({ mode: 'policy', flag: { ...f } }); }
  function closeModal() { setModal({ mode: null, flag: null }); }

  async function performToggle(f: Flag, nextEnabled: boolean) {
    const res = await actions.toggleFlag(f.name, nextEnabled);
    if (!res.success) { setFeedback(res.message); return; }
    try { await actions.refreshFlags(); } catch { }
  }

  async function handleToggle(f: Flag) {
    const nextEnabled = !f.enabled;
    if (nextEnabled && f.mutex_with) {
      const other = flags.find(flag => flag.name === f.mutex_with);
      if (other?.enabled) {
        setMutexConfirm({ flag: f, other });
        return;
      }
    }
    await performToggle(f, nextEnabled);
  }

  function handleAdd() {
    setModal({ mode: 'edit', flag: { name: '', enabled: false, description: '', protected: false, mutex_with: '' } });
  }

  async function submitEdit(f: Flag, isNew: boolean) {
    const res = isNew
      ? await actions.addFlag(f.name, f.description, f.enabled)
      : await actions.editFlag(f.name, f.description, f.enabled);
    if (res.success) { closeModal(); try { await actions.refreshFlags(); } catch { } }
    else { setFeedback(res.message); }
  }

  async function submitDelete(f: Flag) {
    const res = await actions.deleteFlag(f.name);
    if (res.success) { closeModal(); try { await actions.refreshFlags(); } catch { } }
    else { setFeedback(res.message); }
  }

  async function submitPolicy(f: Flag) {
    const res = await actions.setFlagPolicy(f.name, f.protected, f.mutex_with);
    if (res.success) { closeModal(); try { await actions.refreshFlags(); } catch { } }
    else { setFeedback(res.message); }
  }

  async function confirmMutexToggle() {
    if (!mutexConfirm) return;
    const { flag } = mutexConfirm;
    setMutexConfirm(null);
    await performToggle(flag, true);
  }

  const isNew = modal.mode === 'edit' && modal.flag?.name === '';

  return (
    <div className="flex flex-col h-full bg-(--c-panel) border border-(--c-border) rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-(--c-border)">
        <span className="text-xs font-semibold text-(--c-t1) uppercase tracking-wider">Feature Flags</span>
        <div className="flex items-center gap-2">
          <button
            onClick={handleAdd}
            className="px-3 py-1 text-xs rounded bg-[#6366f1] hover:bg-indigo-500 text-white transition-colors"
          >
            + Add Flag
          </button>
          <button onClick={onClose} className="text-(--c-t2) hover:text-(--c-t1) text-sm leading-none px-1">✕</button>
        </div>
      </div>

      {feedback && (
        <div className="mx-4 mt-2 px-3 py-2 rounded bg-[#ef4444]/10 border border-[#ef4444]/30 text-[#ef4444] text-xs flex justify-between">
          <span>{feedback}</span>
          <button onClick={() => setFeedback(null)} className="ml-2 opacity-60 hover:opacity-100">✕</button>
        </div>
      )}

      <div className="overflow-auto flex-1">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-(--c-border) text-(--c-t2) text-xs">
              <th className="text-left px-4 py-2 font-medium">Name</th>
              <th className="text-left px-4 py-2 font-medium">Status</th>
              <th className="text-left px-4 py-2 font-medium">Description</th>
              <th className="text-left px-4 py-2 font-medium">Policy</th>
              <th className="px-4 py-2 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {flags.length === 0 && (
              <tr>
                <td colSpan={5} className="text-center py-8 text-(--c-t2)">No flags. Click + Add Flag to create one.</td>
              </tr>
            )}
            {flags.map(f => (
              <tr key={f.name} className="border-b border-(--c-row-border) hover:bg-(--c-row) transition-colors">
                <td className="px-4 py-2.5">
                  <span className="font-mono text-(--c-t1)">{f.name}</span>
                </td>
                <td className="px-4 py-2.5">
                  <Toggle enabled={f.enabled} onChange={() => handleToggle(f)} />
                </td>
                <td className="px-4 py-2.5 text-(--c-t3) max-w-xs truncate">{f.description || '—'}</td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {f.protected && (
                      <span className="px-1.5 py-0.5 text-[10px] rounded bg-(--c-warn-bg) border border-(--c-warn-border) text-(--c-warn-text)">Protected</span>
                    )}
                    {f.mutex_with && (
                      <span className="px-1.5 py-0.5 text-[10px] rounded bg-(--c-info-bg) border border-(--c-info-border) text-(--c-info-text) font-mono">
                        mutex ↔ {f.mutex_with}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-right">
                  <div className="relative inline-block">
                    <button
                      onClick={e => { e.stopPropagation(); setOpenMenu(openMenu === f.name ? null : f.name); }}
                      className="w-7 h-7 flex items-center justify-center rounded text-(--c-t2) hover:text-(--c-t1) hover:bg-(--c-muted) transition-colors text-lg leading-none"
                      title="Actions"
                    >
                      ⋮
                    </button>
                    {openMenu === f.name && (
                      <div className="absolute right-0 top-8 z-20 min-w-[120px] bg-(--c-panel) border border-(--c-border) rounded-lg shadow-xl overflow-hidden">
                        <button
                          onClick={() => { openEdit(f); setOpenMenu(null); }}
                          className="w-full text-left px-3 py-2 text-sm text-(--c-t1) hover:bg-(--c-muted) transition-colors"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => { openPolicy(f); setOpenMenu(null); }}
                          className="w-full text-left px-3 py-2 text-sm text-(--c-t1) hover:bg-(--c-muted) transition-colors"
                        >
                          Policy
                        </button>
                        <div className="border-t border-(--c-border)" />
                        <button
                          onClick={() => { openDelete(f); setOpenMenu(null); }}
                          className="w-full text-left px-3 py-2 text-sm text-[#ef4444] hover:bg-(--c-muted) transition-colors"
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {mutexConfirm && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
          <div className="bg-(--c-panel) border border-(--c-border) rounded-lg p-5 w-full max-w-md shadow-2xl">
            <h3 className="text-(--c-t1) font-medium mb-3">Disable mutex pair?</h3>
            <p className="text-(--c-t2) text-sm mb-4">
              Enabling "{mutexConfirm.flag.name}" will disable "{mutexConfirm.other.name}".
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setMutexConfirm(null)}
                className="px-4 py-1.5 text-sm rounded bg-(--c-muted) text-(--c-t1) hover:bg-(--c-hover)"
              >
                Cancel
              </button>
              <button
                onClick={confirmMutexToggle}
                className="px-4 py-1.5 text-sm rounded bg-[#6366f1] text-white hover:bg-indigo-500"
              >
                Disable & Enable
              </button>
            </div>
          </div>
        </div>
      )}

      {modal.mode && modal.flag && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
          <div className="bg-(--c-panel) border border-(--c-border) rounded-lg p-5 w-full max-w-md shadow-2xl">
            {modal.mode === 'delete' && (
              <>
                <h3 className="text-(--c-t1) font-medium mb-3">Delete flag "{modal.flag.name}"?</h3>
                <p className="text-(--c-t2) text-sm mb-4">This action cannot be undone.</p>
                <div className="flex justify-end gap-2">
                  <button onClick={closeModal} className="px-4 py-1.5 text-sm rounded bg-(--c-muted) text-(--c-t1) hover:bg-(--c-hover)">Cancel</button>
                  <button onClick={() => submitDelete(modal.flag!)} className="px-4 py-1.5 text-sm rounded bg-[#ef4444] text-white hover:bg-red-500">Delete</button>
                </div>
              </>
            )}

            {modal.mode === 'edit' && (
              <EditForm
                flag={modal.flag}
                isNew={isNew}
                onChange={f => setModal(m => ({ ...m, flag: f }))}
                onSubmit={() => submitEdit(modal.flag!, isNew)}
                onCancel={closeModal}
              />
            )}

            {modal.mode === 'policy' && (
              <PolicyForm
                flag={modal.flag}
                onChange={f => setModal(m => ({ ...m, flag: f }))}
                onSubmit={() => submitPolicy(modal.flag!)}
                onCancel={closeModal}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function EditForm({ flag, isNew, onChange, onSubmit, onCancel }: {
  flag: Flag; isNew: boolean;
  onChange: (f: Flag) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  return (
    <>
      <h3 className="text-(--c-t1) font-medium mb-4">{isNew ? 'Add Flag' : `Edit "${flag.name}"`}</h3>
      <div className="space-y-3">
        {isNew && (
          <div>
            <label className="block text-xs text-(--c-t2) mb-1">Name</label>
            <input
              value={flag.name}
              onChange={e => onChange({ ...flag, name: e.target.value })}
              className="w-full bg-(--c-inp) border border-(--c-border) rounded px-3 py-1.5 text-sm text-(--c-t1) focus:outline-none focus:border-[#6366f1]"
              placeholder="my-feature-flag"
            />
          </div>
        )}
        <div>
          <label className="block text-xs text-(--c-t2) mb-1">Description</label>
          <input
            value={flag.description}
            onChange={e => onChange({ ...flag, description: e.target.value })}
            className="w-full bg-(--c-inp) border border-(--c-border) rounded px-3 py-1.5 text-sm text-(--c-t1) focus:outline-none focus:border-[#6366f1]"
            placeholder="What does this flag do?"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-(--c-t2)">Enabled</label>
          <button
            onClick={() => onChange({ ...flag, enabled: !flag.enabled })}
            className={`relative inline-flex items-center h-6 w-11 shrink-0 cursor-pointer rounded-full p-0.5 transition-colors ${flag.enabled ? 'bg-[#22c55e]' : 'bg-(--c-muted)'}`}
          >
            <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${flag.enabled ? 'translate-x-5' : 'translate-x-0'}`} />
          </button>
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button onClick={onCancel} className="px-4 py-1.5 text-sm rounded bg-(--c-muted) text-(--c-t1) hover:bg-(--c-hover)">Cancel</button>
        <button onClick={onSubmit} className="px-4 py-1.5 text-sm rounded bg-[#6366f1] text-white hover:bg-indigo-500">
          {isNew ? 'Create' : 'Save'}
        </button>
      </div>
    </>
  );
}

function PolicyForm({ flag, onChange, onSubmit, onCancel }: {
  flag: Flag;
  onChange: (f: Flag) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  return (
    <>
      <h3 className="text-(--c-t1) font-medium mb-4">Policy — "{flag.name}"</h3>
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <button
            onClick={() => onChange({ ...flag, protected: !flag.protected })}
            className={`relative inline-flex items-center h-6 w-11 shrink-0 cursor-pointer rounded-full p-0.5 transition-colors ${flag.protected ? 'bg-[#eab308]' : 'bg-(--c-muted)'}`}
          >
            <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${flag.protected ? 'translate-x-5' : 'translate-x-0'}`} />
          </button>
          <label className="text-sm text-(--c-t1)">Protected <span className="text-(--c-t2) text-xs">(cannot be disabled)</span></label>
        </div>
        <div>
          <label className="block text-xs text-(--c-t2) mb-1">Mutually exclusive with <span className="text-(--c-t3)">(flag name, or leave blank)</span></label>
          <input
            value={flag.mutex_with}
            onChange={e => onChange({ ...flag, mutex_with: e.target.value })}
            className="w-full bg-(--c-inp) border border-(--c-border) rounded px-3 py-1.5 text-sm text-(--c-t1) focus:outline-none focus:border-[#6366f1]"
            placeholder="other-flag-name"
          />
          {flag.mutex_with && (
            <p className="mt-1.5 text-[11px] text-[#a5b4fc]">When this flag is ON, <strong>{flag.mutex_with}</strong> will be forced OFF, and vice versa.</p>
          )}
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button onClick={onCancel} className="px-4 py-1.5 text-sm rounded bg-(--c-muted) text-(--c-t1) hover:bg-(--c-hover)">Cancel</button>
        <button onClick={onSubmit} className="px-4 py-1.5 text-sm rounded bg-[#6366f1] text-white hover:bg-indigo-500">Save Policy</button>
      </div>
    </>
  );
}
