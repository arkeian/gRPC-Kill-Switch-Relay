import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { io, Socket } from 'socket.io-client';
import type { Flag, FlagUpdate, AuditRecord, GrusStatus, PolicyRules, InitialState } from './types';

export interface SocketState {
  flags: Flag[];
  eventLog: FlagUpdate[];
  auditRecords: AuditRecord[];
  grusStatus: GrusStatus;
  policyRules: PolicyRules;
  connected: boolean;
  shutdownSeconds: number | null;
}

export interface SocketActions {
  toggleFlag: (name: string, enabled: boolean, reason?: string) => Promise<{ success: boolean; message: string }>;
  addFlag: (name: string, description: string, enabled: boolean, reason?: string) => Promise<{ success: boolean; message: string }>;
  editFlag: (name: string, description: string, enabled: boolean, reason?: string) => Promise<{ success: boolean; message: string }>;
  deleteFlag: (name: string, reason?: string) => Promise<{ success: boolean; message: string }>;
  validateChange: (current: Partial<Flag>, proposed: Partial<Flag>) => Promise<{ approved: boolean; denial_reason: string }>;
  refreshFlags: () => Promise<void>;
  getAuditHistory: (opts: { flag_name?: string; limit: number; offset: number }) => Promise<AuditRecord[]>;
  setFlagPolicy: (flag_name: string, protected_: boolean, mutex_with: string) => Promise<{ success: boolean; message: string }>;
  keepAlive: () => void;
  setEventLogActive: (active: boolean) => void;
}

const DEFAULT_STATUS: GrusStatus = { flag_store: false, policy_evaluator: false, broadcaster: false, audit_logger: false };
const DEFAULT_RULES: PolicyRules = { protected_flags: [], mutex_pairs: [] };

const MAX_EVENT_LOG = 200;

export function useSocket(): [SocketState, SocketActions] {
  const socketRef = useRef<Socket | null>(null);
  const eventLogActiveRef = useRef(true);
  const [state, setState] = useState<SocketState>({
    flags: [],
    eventLog: [],
    auditRecords: [],
    grusStatus: DEFAULT_STATUS,
    policyRules: DEFAULT_RULES,
    connected: false,
    shutdownSeconds: null,
  });

  useEffect(() => {
    const socket = io({ path: '/socket.io/', transports: ['websocket'] });
    socketRef.current = socket;

    socket.on('connect', () => setState(s => ({ ...s, connected: true })));
    socket.on('disconnect', () => setState(s => ({ ...s, connected: false })));

    socket.on('initial_state', (data: InitialState) => {
      setState(s => ({
        ...s,
        flags: data.flags,
        grusStatus: data.grus_status ?? DEFAULT_STATUS,
        policyRules: data.policy_rules ?? DEFAULT_RULES,
      }));
    });

    socket.on('flag_update', (update: FlagUpdate) => {
      setState(s => {
        let flags = s.flags.filter(f => f.name !== update.name);
        if (update.change_type !== 'DELETED') {
          flags = [
            ...flags.filter(f => f.name < update.name),
            {
              name: update.name,
              enabled: update.enabled,
              description: update.description,
              protected: update.protected,
              mutex_with: update.mutex_with,
            },
            ...flags.filter(f => f.name >= update.name),
          ];
          flags.sort((a, b) => a.name.localeCompare(b.name));
        }
        if (!eventLogActiveRef.current) return { ...s, flags };
        const key = `${update.name}:${update.change_type}:${update.timestamp}:${update.enabled ? 1 : 0}`;
        const hasEvent = s.eventLog.some(ev => (
          `${ev.name}:${ev.change_type}:${ev.timestamp}:${ev.enabled ? 1 : 0}` === key
        ));
        const eventLog = hasEvent ? s.eventLog : [update, ...s.eventLog].slice(0, MAX_EVENT_LOG);
        return { ...s, flags, eventLog };
      });
    });

    socket.on('audit_record', (record: AuditRecord) => {
      setState(s => ({ ...s, auditRecords: [record, ...s.auditRecords].slice(0, MAX_EVENT_LOG) }));
    });

    socket.on('grus_status', (status: GrusStatus) => {
      setState(s => ({ ...s, grusStatus: status }));
    });

    socket.on('policy_update', (rules: PolicyRules) => {
      setState(s => ({ ...s, policyRules: rules }));
    });

    socket.on('shutdown_warning', (data: { seconds_remaining: number }) => {
      setState(s => ({ ...s, shutdownSeconds: data.seconds_remaining }));
    });

    return () => { socket.disconnect(); };
  }, []);

  const emit = useCallback(<T>(event: string, data?: unknown): Promise<T> => {
    return new Promise((resolve, reject) => {
      const socket = socketRef.current;
      if (!socket) { reject(new Error('Not connected')); return; }
      if (data !== undefined) {
        socket.emit(event, data, resolve);
      } else {
        socket.emit(event, {}, resolve);
      }
    });
  }, []);

  const actions: SocketActions = useMemo(() => ({
    toggleFlag: (name, enabled, reason = '') =>
      emit('toggle_flag', { name, enabled, reason }),

    addFlag: (name, description, enabled, reason = '') =>
      emit('add_flag', { name, description, enabled, reason }),

    editFlag: (name, description, enabled, reason = '') =>
      emit('edit_flag', { name, description, enabled, reason }),

    deleteFlag: (name, reason = '') =>
      emit('delete_flag', { name, reason }),

    validateChange: (current, proposed) =>
      emit('validate_change', { current, proposed }),

    refreshFlags: async () => {
      const resp = await emit<{ flags: Flag[] }>('refresh_flags');
      setState(s => ({ ...s, flags: resp.flags }));
    },

    getAuditHistory: async (opts) => {
      const resp = await emit<{ records: AuditRecord[] }>('get_audit_history', opts);
      return resp.records ?? [];
    },

    setFlagPolicy: (flag_name, protected_, mutex_with) =>
      emit('set_flag_policy', { flag_name, protected: protected_, mutex_with }),

    keepAlive: () => {
      socketRef.current?.emit('keep_alive', {});
      setState(s => ({ ...s, shutdownSeconds: null }));
    },

    setEventLogActive: (active: boolean) => {
      eventLogActiveRef.current = active;
      if (!active) setState(s => ({ ...s, eventLog: [] }));
    },
  }), [emit]);

  return [state, actions];
}
