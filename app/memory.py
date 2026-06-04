"""一天记忆：把群里最近的消息(文字 + 已整理的语音转写)存进 SQLite，
喂给 DeepSeek 整理时当上下文，帮助保持人名/地名/用词一致。

最佳努力(best-effort)：DB 错误一律吞掉并降级，绝不影响转写主流程。
config 全部在调用时读取，方便测试 monkeypatch。
"""
import logging
import sqlite3
import time

from . import config

logger = logging.getLogger("memory")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    ts      REAL    NOT NULL,
    speaker TEXT    NOT NULL,
    text    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_chat_ts ON memory(chat_id, ts);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(_SCHEMA)  # CREATE IF NOT EXISTS，幂等
    return conn


def init() -> None:
    """启动时建表。失败只记日志(best-effort)。"""
    _connect().close()


def add(chat_id: int, text: str, *, ts: float, speaker: str = "") -> None:
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT INTO memory (chat_id, ts, speaker, text) VALUES (?, ?, ?, ?)",
            (chat_id, ts, speaker or "", text),
        )
    conn.close()


def recent(chat_id: int) -> list[str]:
    cutoff = time.time() - config.MEMORY_WINDOW_HOURS * 3600
    conn = _connect()
    with conn:
        conn.execute("DELETE FROM memory WHERE ts < ?", (cutoff,))  # 顺手清过期
        rows = conn.execute(
            "SELECT speaker, text FROM memory WHERE chat_id = ? AND ts >= ? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (chat_id, cutoff, config.MEMORY_MAX_MESSAGES),
        ).fetchall()
    conn.close()
    rows.reverse()  # 取最近 N 条后，倒回成 旧→新
    return [r[1] for r in rows]
