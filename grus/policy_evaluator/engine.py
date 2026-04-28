import datetime
import logging
import os
import threading

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli

_rules_path = os.environ.get('GRUS_POLICY_CONFIG', '')
_rules_mtime: float | None = None
_rules_lock = threading.Lock()

PROTECTED_FLAGS: set[str] = set(['payment-fallback'])
MUTEX_PAIRS: list[tuple[str, str]] = [('cache-only-mode', 'disable-cache-refresh')]

_TZ_JAKARTA = datetime.timezone(datetime.timedelta(hours=7))
MAINTENANCE_WINDOW_LOCAL = (2, 4)


def _load_rules_from_file(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    with open(path, 'rb') as f:
        return tomli.load(f)


def _apply_rules(rules: dict) -> None:
    global PROTECTED_FLAGS, MUTEX_PAIRS, _TZ_JAKARTA, MAINTENANCE_WINDOW_LOCAL

    protected_flags = rules.get('protected_flags', ['payment-fallback'])
    if not isinstance(protected_flags, list):
        protected_flags = ['payment-fallback']
    PROTECTED_FLAGS = set(str(x) for x in protected_flags)

    mutex_groups = rules.get('mutual_exclusion', [{'flags': ['cache-only-mode', 'disable-cache-refresh']}])
    pairs: list[tuple[str, str]] = []
    if isinstance(mutex_groups, list):
        for group in mutex_groups:
            if not isinstance(group, dict):
                continue
            flags = group.get('flags', [])
            if isinstance(flags, list) and len(flags) == 2:
                a, b = str(flags[0]), str(flags[1])
                if a and b and a != b:
                    pairs.append((a, b))
    MUTEX_PAIRS = pairs

    mw = rules.get('maintenance_window', {}) if isinstance(rules.get('maintenance_window', {}), dict) else {}
    tz_offset = int(mw.get('timezone_offset', 7))
    _TZ_JAKARTA = datetime.timezone(datetime.timedelta(hours=tz_offset))
    MAINTENANCE_WINDOW_LOCAL = (int(mw.get('start_hour', 2)), int(mw.get('end_hour', 4)))


def _reload_rules_if_needed() -> None:
    global _rules_mtime
    if not _rules_path or not os.path.isfile(_rules_path):
        return
    try:
        mtime = os.path.getmtime(_rules_path)
    except OSError:
        return

    with _rules_lock:
        if _rules_mtime == mtime:
            return
        try:
            rules = _load_rules_from_file(_rules_path)
            _apply_rules(rules)
            _rules_mtime = mtime
        except Exception:
            # If reload fails, keep the last known-good rules.
            return


_reload_rules_if_needed()


def _persist_rules() -> None:
    global _rules_mtime
    if not _rules_path:
        return
    with _rules_lock:
        protected = list(PROTECTED_FLAGS)
        pairs = list(MUTEX_PAIRS)
        mw_start, mw_end = MAINTENANCE_WINDOW_LOCAL
        tz_offset = int(_TZ_JAKARTA.utcoffset(None).total_seconds() / 3600)
    lines = []
    items = ', '.join(f'"{f}"' for f in sorted(protected))
    lines.append(f'protected_flags = [{items}]')
    lines.append('')
    for a, b in pairs:
        lines.append('[[mutual_exclusion]]')
        lines.append(f'flags = ["{a}", "{b}"]')
        lines.append('')
    lines.append('[maintenance_window]')
    lines.append(f'start_hour = {mw_start}')
    lines.append(f'end_hour = {mw_end}')
    lines.append(f'timezone_offset = {tz_offset}')
    try:
        with open(_rules_path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        _rules_mtime = os.path.getmtime(_rules_path)
    except OSError as e:
        logging.getLogger(__name__).warning("Failed to persist policy rules: %s", e)


def get_policy_rules() -> dict:
    _reload_rules_if_needed()
    with _rules_lock:
        return {
            'protected_flags': list(PROTECTED_FLAGS),
            'mutex_pairs': list(MUTEX_PAIRS),
        }


def set_policy_rules(protected_flags: list, mutex_pairs: list) -> None:
    global PROTECTED_FLAGS, MUTEX_PAIRS
    with _rules_lock:
        PROTECTED_FLAGS = set(str(f) for f in protected_flags)
        MUTEX_PAIRS = [(str(a), str(b)) for a, b in mutex_pairs]
    _persist_rules()


def prune_flag(flag_name: str) -> None:
    global PROTECTED_FLAGS, MUTEX_PAIRS
    with _rules_lock:
        PROTECTED_FLAGS.discard(flag_name)
        MUTEX_PAIRS = [(a, b) for a, b in MUTEX_PAIRS if a != flag_name and b != flag_name]
    _persist_rules()


def validate_change(proposed_flag, context_flags):
    _reload_rules_if_needed()
    current_state = {f.name: f.enabled for f in context_flags}

    if proposed_flag.name in PROTECTED_FLAGS and not proposed_flag.enabled:
        return False, (
            f"'{proposed_flag.name}' is a protected flag and cannot be disabled."
        )

    for flag_a, flag_b in MUTEX_PAIRS:
        if proposed_flag.name == flag_a and proposed_flag.enabled:
            if current_state.get(flag_b, False):
                return False, (
                    f"'{flag_a}' and '{flag_b}' are mutually exclusive: "
                    f"'{flag_b}' is already enabled."
                )
        elif proposed_flag.name == flag_b and proposed_flag.enabled:
            if current_state.get(flag_a, False):
                return False, (
                    f"'{flag_a}' and '{flag_b}' are mutually exclusive: "
                    f"'{flag_a}' is already enabled."
                )

    current_hour = datetime.datetime.now(_TZ_JAKARTA).hour
    start, end = MAINTENANCE_WINDOW_LOCAL
    if start <= current_hour < end:
        return False, (
            f"Flag changes are blocked during the maintenance window "
            f"({start:02d}:00-{end:02d}:00 UTC+7). Current hour: {current_hour:02d} (UTC+7)."
        )

    return True, ""
