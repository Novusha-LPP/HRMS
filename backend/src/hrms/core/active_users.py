"""Recent authenticated activity for this API process; identities never become labels."""

from collections import OrderedDict
from hashlib import sha256
from hmac import new as hmac_new
from time import monotonic, time

from prometheus_client.core import GaugeMetricFamily

from hrms.core.config import settings


class ActiveUsers:
    window_seconds = 300

    def __init__(self, clock=monotonic, wall_clock=time):
        self.clock = clock
        self.wall_clock = wall_clock
        self.seen = OrderedDict()
        self.history = OrderedDict()

    def _expire(self, now):
        while self.seen:
            key, at = next(iter(self.seen.items()))
            if now - at < self.window_seconds:
                break
            del self.seen[key]

    def record(self, tenant_id, user_id):
        now = self.clock()
        self._expire(now)
        key = (tenant_id, user_id)
        self.seen[key] = now
        self.seen.move_to_end(key)
        # Stable opaque IDs allow distinct counting across scrapes and instances,
        # without exporting account IDs or tenant IDs. Logout retains past activity.
        opaque_id = hmac_new(
            settings.secret_key.encode(), f"{tenant_id}:{user_id}".encode(), sha256
        ).hexdigest()
        self.history[opaque_id] = (now, self.wall_clock())
        self.history.move_to_end(opaque_id)
        self._expire_history(now)

    def _expire_history(self, now):
        while self.history:
            key, (at, _) = next(iter(self.history.items()))
            if now - at < 30 * 86400:
                break
            del self.history[key]

    def remove(self, tenant_id, user_id):
        self.seen.pop((tenant_id, user_id), None)

    def count(self):
        self._expire(self.clock())
        return len(self.seen)

    def collect(self):
        metric = GaugeMetricFamily(
            "hrms_active_users",
            "Distinct authenticated users active in the last 5 minutes in this API process",
        )
        metric.add_metric([], self.count())
        yield metric
        self._expire_history(self.clock())
        history = GaugeMetricFamily(
            "hrms_user_last_activity_timestamp_seconds",
            "Last successful authenticated activity, with an opaque user fingerprint",
            labels=["user_fingerprint"],
        )
        for fingerprint, (_, timestamp) in self.history.items():
            history.add_metric([fingerprint], timestamp)
        yield history


active_users = ActiveUsers()
