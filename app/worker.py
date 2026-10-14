"""Worker entry point. M1 is a no-op heartbeat loop; M8 wires up the queue."""
from __future__ import annotations

import os
import signal
import socket
import time
from datetime import datetime, timezone

from sqlmodel import Session

from .config import get_settings
from .db import get_engine
from .models.heartbeat import Heartbeat
from .security import assert_safe_secret_key


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def run() -> None:
    """M1 heartbeat loop. Replaced by the real job loop in M8; the heart beat
    table and the route it powers already work."""
    assert_safe_secret_key()
    s = get_settings()
    wid = _worker_id()
    stop = {"v": False}

    def _stop(*_a):
        stop["v"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    while not stop["v"]:
        try:
            with Session(get_engine()) as sess:
                row = sess.get(Heartbeat, wid)
                if row is None:
                    row = Heartbeat(worker_id=wid, last_seen=datetime.now(timezone.utc))
                    sess.add(row)
                else:
                    row.last_seen = datetime.now(timezone.utc)
                sess.commit()
        except Exception:
            # Don't crash on transient DB issues; just retry.
            pass
        time.sleep(max(5, s.heartbeat_interval_seconds))


if __name__ == "__main__":
    run()
