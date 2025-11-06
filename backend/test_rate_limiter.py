#!/usr/bin/env python3
"""
Quick test to demonstrate the RateLimiter class behavior.
This simulates API calls and shows how the rate limiter throttles them.
"""
import time
from threading import Thread
from collections import deque
from threading import Lock


class RateLimiter:
    """
    Thread-safe rate limiter that ensures no more than max_requests per time_window.
    Uses a sliding window approach with deque to track request timestamps.
    """
    def __init__(self, max_requests=10, time_window=60):
        """
        Args:
            max_requests: Maximum number of requests allowed per time window
            time_window: Time window in seconds (default: 60 for per-minute limiting)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = Lock()
    
    def acquire(self):
        """
        Block until a request slot is available, respecting the rate limit.
        This method is thread-safe and will sleep if necessary to maintain the rate.
        """
        with self.lock:
            now = time.time()
            
            # Remove requests older than the time window
            while self.requests and self.requests[0] <= now - self.time_window:
                self.requests.popleft()
            
            # If we're at the limit, wait until the oldest request expires
            if len(self.requests) >= self.max_requests:
                sleep_time = self.requests[0] + self.time_window - now
                if sleep_time > 0:
                    print(f"  [RATE LIMIT] Sleeping {sleep_time:.1f}s to respect limit...")
                    time.sleep(sleep_time)
                # Clean up again after sleeping
                now = time.time()
                while self.requests and self.requests[0] <= now - self.time_window:
                    self.requests.popleft()
            
            # Record this request
            self.requests.append(now)


def simulate_api_call(worker_id, rate_limiter, start_time):
    """Simulate a worker making an API call."""
    elapsed = time.time() - start_time
    print(f"[{elapsed:5.1f}s] Worker {worker_id}: Requesting rate limit slot...")
    
    rate_limiter.acquire()
    
    elapsed = time.time() - start_time
    print(f"[{elapsed:5.1f}s] Worker {worker_id}: ✅ Got slot! Making API call...")
    
    # Simulate API processing time
    time.sleep(0.5)
    
    elapsed = time.time() - start_time
    print(f"[{elapsed:5.1f}s] Worker {worker_id}: Done")


def test_rate_limiter_demo():
    """
    Demo: 5 workers trying to process 15 requests with a 10 req/10sec limit.
    
    Expected behavior:
    - First 10 requests go through immediately
    - Remaining 5 wait until the time window allows
    """
    print("=" * 60)
    print("RATE LIMITER TEST")
    print("=" * 60)
    print("Settings: 10 requests per 10 seconds")
    print("Test: 5 workers, 15 total requests")
    print("Expected: First 10 immediate, next 5 throttled")
    print("=" * 60)
    print()
    
    # Use shorter time window for demo (10 seconds instead of 60)
    rate_limiter = RateLimiter(max_requests=10, time_window=10)
    start_time = time.time()
    
    threads = []
    for i in range(15):
        t = Thread(target=simulate_api_call, args=(i+1, rate_limiter, start_time))
        threads.append(t)
        t.start()
        time.sleep(0.1)  # Stagger starts slightly
    
    # Wait for all to complete
    for t in threads:
        t.join()
    
    total_time = time.time() - start_time
    print()
    print("=" * 60)
    print(f"✅ All 15 requests completed in {total_time:.1f}s")
    print(f"Expected: ~10-11s (10 req immediately + 5 after 10s window)")
    print("=" * 60)


if __name__ == '__main__':
    test_rate_limiter_demo()
