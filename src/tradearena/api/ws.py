"""WebSocket real-time broadcast for the trading floor UI."""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Maximum number of recent messages kept for replay on reconnect
_MAX_QUEUE_SIZE = 50


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events.

    Keeps a bounded queue of recent messages so reconnecting clients
    can catch up on events they missed.
    """

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._queue: deque[dict] = deque(maxlen=_MAX_QUEUE_SIZE)
        self._seq: int = 0

    async def connect(self, ws: WebSocket, last_seq: int = 0) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WS connected (%d total)", len(self._connections))
        # Replay missed messages if client provides a last_seq
        if last_seq > 0:
            missed = [m for m in self._queue if m["seq"] > last_seq]
            for m in missed:
                try:
                    await ws.send_text(json.dumps(m))
                except Exception:
                    break

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info("WS disconnected (%d total)", len(self._connections))

    async def broadcast(self, event: str, data: Any = None) -> None:
        """Send a JSON message to all connected clients and enqueue for replay."""
        self._seq += 1
        message = {"event": event, "data": data, "seq": self._seq, "ts": time.time()}
        self._queue.append(message)
        payload = json.dumps(message)
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    @property
    def current_seq(self) -> int:
        """Current sequence number for clients to track position."""
        return self._seq


manager = ConnectionManager()
