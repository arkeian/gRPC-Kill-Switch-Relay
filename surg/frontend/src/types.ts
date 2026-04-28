export interface Flag {
  name: string;
  enabled: boolean;
  description: string;
  protected: boolean;
  mutex_with: string;
}

export interface MutexPair {
  flag_a: string;
  flag_b: string;
}

export interface PolicyRules {
  protected_flags: string[];
  mutex_pairs: MutexPair[];
}

export interface GrusStatus {
  flag_store: boolean;
  policy_evaluator: boolean;
  broadcaster: boolean;
  audit_logger: boolean;
}

export interface FlagUpdate {
  name: string;
  enabled: boolean;
  description: string;
  protected: boolean;
  mutex_with: string;
  old_value: boolean;
  changed_by: string;
  timestamp: number;
  change_type: string;
}

export interface AuditRecord {
  flag_name: string;
  old_value: boolean;
  new_value: boolean;
  changed_by: string;
  changed_at: number;
  reason: string;
  policy_result: string;
}

export interface InitialState {
  flags: Flag[];
  grus_status: GrusStatus;
  policy_rules: PolicyRules;
}
