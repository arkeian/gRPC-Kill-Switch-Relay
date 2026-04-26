import logging
import queue
import threading

log = logging.getLogger(__name__)

# Sentinel object: penanda khusus untuk memberi sinyal shutdown ke subscriber (graceful shutdown)

_SENTINEL = object() 

class SubscriberManager:

    def __init__(self):
        self._subscribers = []
        self._lock = threading.Lock()

    # Menambahkan Subscriber Baru

    def add(self, q):
        with self._lock:
            self._subscribers.append(q)
        log.info("Subscriber added (total: %d)", len(self._subscribers))

    # Menghapus Subscriber

    def remove(self, q):
        with self._lock:
            self._subscribers.remove(q)
        log.info("Subscriber removed (total: %d)", len(self._subscribers))

    # Broadcast Perubahan Flag ke Subscriber

    def notify_all(self, update):
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(update)
        log.info("Notified %d subscriber(s): flag='%s'", len(subscribers), update.flag.name)

    # Memberi Sinyal Shutdown ke Subscriber

    def shutdown(self):
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(_SENTINEL)
