import logging
import queue
import threading

log = logging.getLogger(__name__)

_SENTINEL = object()  # pushed to subscriber queues on server shutdown


class SubscriberManager:

    def __init__(self):
        self._subscribers = []      # list[queue.Queue]
        self._lock = threading.Lock()

    def add(self, q):
        with self._lock:
            self._subscribers.append(q)
        log.info("Subscriber added (total: %d)", len(self._subscribers))

    def remove(self, q):
        with self._lock:
            self._subscribers.remove(q)
        log.info("Subscriber removed (total: %d)", len(self._subscribers))

    def notify_all(self, update):
        """Push a FlagUpdate to every active subscriber queue."""
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(update)
        log.info("Notified %d subscriber(s): flag='%s'", len(subscribers), update.flag.name)

    def shutdown(self):
        """Signal all active SubscribeFlags streams to exit cleanly."""
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(_SENTINEL)
