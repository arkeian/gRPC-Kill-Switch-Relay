import datetime

# Rule 1: Flag yang tidak bisa dinonaktifkan (enabled=False)

PROTECTED_FLAGS = {
    "payment-fallback",
}

# Rule 2: Pasangan flag yang saling eksklusif (mutex): tidak boleh keduanya enabled=True secara bersamaan

MUTEX_PAIRS = [
    ("cache-only-mode", "disable-cache-refresh"),
]

# Rule 3: Perubahan flag tidak diizinkan selama jendela pemeliharaan

_TZ_JAKARTA = datetime.timezone(datetime.timedelta(hours=7))
MAINTENANCE_WINDOW_LOCAL = (2, 4)  # 02:00–04:00 UTC+7 (Asia/Jakarta)


def validate_change(proposed_flag, context_flags):
    current_state = {f.name: f.enabled for f in context_flags}

    # Jika flag termasuk protected dan ingin dinonaktifkan: Reject

    if proposed_flag.name in PROTECTED_FLAGS and not proposed_flag.enabled:
        return False, (
            f"'{proposed_flag.name}' is a protected flag and cannot be disabled."
        )

    # Cek apakah ada konflik dengan flag lain yang mutually exclusive

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

    # Cek apakah saat ini berada di dalam jendela pemeliharaan, jika iya: Reject

    current_hour = datetime.datetime.now(_TZ_JAKARTA).hour
    start, end = MAINTENANCE_WINDOW_LOCAL
    if start <= current_hour < end:
        return False, (
            f"Flag changes are blocked during the maintenance window "
            f"({start:02d}:00-{end:02d}:00 UTC+7). Current hour: {current_hour:02d} (UTC+7)."
        )

    # Perubahan flag diizinkan jika lolos semua rule

    return True, ""
