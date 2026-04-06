import datetime
import os

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli

_rules_path = os.environ.get('GRUS_POLICY_CONFIG', '')
_rules = {}
if _rules_path and os.path.isfile(_rules_path):
    with open(_rules_path, 'rb') as _f:
        _rules = tomli.load(_f)

PROTECTED_FLAGS = set(_rules.get('protected_flags', ['payment-fallback']))

MUTEX_PAIRS = [
    tuple(group['flags'])
    for group in _rules.get('mutual_exclusion', [{'flags': ['cache-only-mode', 'disable-cache-refresh']}])
]

_mw = _rules.get('maintenance_window', {})
_TZ_JAKARTA = datetime.timezone(datetime.timedelta(hours=_mw.get('timezone_offset', 7)))
MAINTENANCE_WINDOW_LOCAL = (_mw.get('start_hour', 2), _mw.get('end_hour', 4))


def validate_change(proposed_flag, context_flags):
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
