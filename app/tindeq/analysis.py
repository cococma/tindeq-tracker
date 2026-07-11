"""Force-trace analysis helpers."""


def calculate_rfd(force_history, window_s: float = 0.1) -> float:
    """Max rate of force development (kg/s) over any window up to `window_s`.

    `force_history` is a list of (force_kg, device_ts_us) tuples in device order.
    """
    best_rfd = 0.0
    n = len(force_history)
    for i in range(n):
        f0, t0 = force_history[i]
        for j in range(i + 1, n):
            f1, t1 = force_history[j]
            dt_s = (t1 - t0) / 1_000_000
            if dt_s <= 0:
                continue
            if dt_s > window_s:
                break
            rfd = (f1 - f0) / dt_s
            if rfd > best_rfd:
                best_rfd = rfd
    return best_rfd
