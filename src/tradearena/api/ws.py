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

# Heartbeat settings
PING_INTERVAL_SECONDS = 30
PONG_TIMEOUT_SECONDS = 60


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events.

    Keeps a bounded queue of recent messages so reconnecting clients
    can catch up on events they missed. Sends periodic pings to detect
    and clean up stale connections.
    """

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._last_pong: dict[WebSocket, float] = {}
        self._queue: deque[dict] = deque(maxlen=_MAX_QUEUE_SIZE)
        self._seq: int = 0

    async def connect(self, ws: WebSocket, last_seq: int = 0) -> None:
        await ws.accept()
        self._connections.append(ws)
        self._last_pong[ws] = time.monotonic()
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
        self._last_pong.pop(ws, None)
        logger.info("WS disconnected (%d total)", len(self._connections))

    def record_pong(self, ws: WebSocket) -> None:
        """Record that a client responded (pong or any message)."""
        if ws in self._last_pong:
            self._last_pong[ws] = time.monotonic()

    async def ping_all(self) -> None:
        """Send a ping message to all connected clients and clean up stale ones."""
        now = time.monotonic()
        stale: list[WebSocket] = []

        # Clean up connections that haven't responded within the timeout
        for ws in self._connections:
            last = self._last_pong.get(ws, 0)
            if now - last > PONG_TIMEOUT_SECONDS:
                stale.append(ws)

        for ws in stale:
            logger.info("WS stale connection removed (no pong for %.0fs)", PONG_TIMEOUT_SECONDS)
            try:
                await ws.close(code=1000, reason="pong timeout")
            except Exception:
                pass
            self.disconnect(ws)

        # Send ping to remaining connections
        ping_payload = json.dumps({"event": "ping", "ts": time.time()})
        send_failed: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(ping_payload)
            except Exception:
                send_failed.append(ws)
        for ws in send_failed:
            self.disconnect(ws)

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
