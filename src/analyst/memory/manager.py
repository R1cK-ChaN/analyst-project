from __future__ import annotations

from collections import OrderedDict

from analyst.storage import SQLiteEngineStore

from .session import MemorySession
from .types import MemoryPolicy, MemoryScopeKey


class MemoryManager:
    def __init__(self, store: SQLiteEngineStore, *, max_cached_sessions: int = 256) -> None:
        self.store = store
        self._sessions: OrderedDict[str, MemorySession] = OrderedDict()
        self._max_cached_sessions = max_cached_sessions

    def get_session(
        self,
        scope: MemoryScopeKey,
        *,
        policy: MemoryPolicy | None = None,
    ) -> MemorySession:
        key = scope.storage_key()
        existing = self._sessions.get(key)
        if existing is not None:
            self._sessions.move_to_end(key)
            return existing
        self.store.ensure_memory_scope(scope)
        session = MemorySession(scope=scope, store=self.store, policy=policy or MemoryPolicy())
        self._sessions[key] = session
        if len(self._sessions) > self._max_cached_sessions:
            self._sessions.popitem(last=False)
        return session
