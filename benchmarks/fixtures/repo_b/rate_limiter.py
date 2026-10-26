"""Rate limiter with boundary condition expiration bug."""

import time

class SlidingWindowLimiter:
    def __init__(self, limit: int, window_sec: float):
        self.limit = limit
        self.window_sec = window_sec
        self.requests = []

    def is_allowed(self) -> bool:
        now = time.time()
        # BUG: Retains requests that fall exactly on the window cutoff
        self.requests = [t for t in self.requests if now - t < self.window_sec]
        if len(self.requests) >= self.limit:
            return False
        self.requests.append(now)
        return True
