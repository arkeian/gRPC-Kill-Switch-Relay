import datetime

# ─────────────────────────────────────────────────────────────────────────────
# Rule configuration
# ─────────────────────────────────────────────────────────────────────────────

# Rule 1: These flags can never be disabled (enabled=False).
# payment-fallback must always remain active so downstream services have a
# safe fallback path if the primary payment processor goes down.
PROTECTED_FLAGS = {
    "payment-fallback",
}

# Rule 2: Pairs of flags that cannot both be enabled (enabled=True) at the same
# time.  Each tuple is (flag_a, flag_b).  Enabling either flag while the other
# is already enabled will be denied.
#
# cache-only-mode + disable-cache-refresh: serving from cache while also
# preventing cache refresh means the cache will go stale with no recovery path.
MUTEX_PAIRS = [
    ("cache-only-mode", "disable-cache-refresh"),
]

# Rule 3: No flag changes are allowed during the maintenance window (UTC+7 / Asia/Jakarta).
# Expressed as a [start, end) range of hours.  Adjust the window to test the
# rejection path; keep it narrow so it doesn't block normal demo usage.
_TZ_JAKARTA = datetime.timezone(datetime.timedelta(hours=7))
MAINTENANCE_WINDOW_UTC = (2, 4)  # 02:00–04:00 UTC+7 (Asia/Jakarta)


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def validate_change(proposed_flag, context_flags):
    """Evaluate a proposed flag change against all configured rules.

    Args:
        proposed_flag:  killswitch_pb2.Flag — the desired new state.
        context_flags:  list[killswitch_pb2.Flag] — current state of all flags
                        relevant to mutex evaluation (populated by Flag Store).

    Returns:
        (approved: bool, denial_reason: str)
        denial_reason is empty string when approved.
    """
    # Build a name→enabled lookup from the context flags supplied by the caller.
    current_state = {f.name: f.enabled for f in context_flags}

    # Rule 1 — protected flags cannot be disabled
    if proposed_flag.name in PROTECTED_FLAGS and not proposed_flag.enabled:
        return False, (
            f"'{proposed_flag.name}' is a protected flag and cannot be disabled."
        )

    # Rule 2 — mutex pairs cannot both be enabled simultaneously
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

    # Rule 3 — maintenance window blocks all changes
    current_hour = datetime.datetime.now(_TZ_JAKARTA).hour
    start, end = MAINTENANCE_WINDOW_UTC
    if start <= current_hour < end:
        return False, (
            f"Flag changes are blocked during the maintenance window "
            f"({start:02d}:00–{end:02d}:00 UTC+7). Current hour: {current_hour:02d} (UTC+7)."
        )

    return True, ""
