"""Durable, exclusive checkpoints for one local benchmark run."""

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path


@contextmanager
def checkpoint(path, identity, task_ids, resume=False):
    directory = Path(path)
    if directory.is_symlink():
        raise ValueError("Checkpoint directory cannot be a symbolic link")
    if resume:
        if not directory.is_dir() or not (directory / "replies.sqlite3").is_file():
            raise ValueError("No saved checkpoint to resume")
    else:
        directory.mkdir(parents=True, mode=0o700)
    lock_path, data_path = directory / "lock.sqlite3", directory / "replies.sqlite3"
    if any(p.is_symlink() or (p.exists() and not p.is_file()) for p in (lock_path, data_path)):
        raise ValueError("Checkpoint files must be regular files")

    try:
        with closing(sqlite3.connect(lock_path, timeout=0)) as lock:
            try:
                lock.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                raise ValueError("Checkpoint is locked by another run, or its lock is unavailable") from error
            with closing(sqlite3.connect(data_path, timeout=0)) as db:
                db.execute("CREATE TABLE IF NOT EXISTS run (identity TEXT NOT NULL, started TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS replies (task_id TEXT PRIMARY KEY, reply TEXT NOT NULL)")
                metadata = db.execute("SELECT identity, started FROM run").fetchall()
                if resume:
                    if len(metadata) != 1 or metadata[0][0] != identity:
                        raise ValueError("Checkpoint belongs to a different dataset or configuration")
                    started = metadata[0][1]
                else:
                    started = datetime.now(UTC).isoformat()
                    with db:
                        db.execute("INSERT INTO run VALUES (?, ?)", (identity, started))
                saved = {}
                for task_id, payload in db.execute("SELECT task_id, reply FROM replies"):
                    if task_id not in task_ids or len(payload) > 100_000:
                        raise ValueError("Checkpoint contains an invalid reply record")
                    reply = json.loads(payload)
                    if not isinstance(reply, dict):
                        raise ValueError("Checkpoint reply must be an object")
                    saved[task_id] = reply

                def record(task_id, reply):
                    if task_id not in task_ids or task_id in saved:
                        raise ValueError("Invalid or duplicate checkpoint task ID")
                    payload = json.dumps(reply, ensure_ascii=False, allow_nan=False)
                    if len(payload) > 100_000:
                        reply = {"error": "Response exceeded the checkpoint record limit"}
                        payload = json.dumps(reply)
                    with db:
                        db.execute("INSERT INTO replies VALUES (?, ?)", (task_id, payload))
                    saved[task_id] = reply

                yield saved, record, started
    except sqlite3.Error as error:
        raise ValueError("Checkpoint database is unreadable or busy") from error
