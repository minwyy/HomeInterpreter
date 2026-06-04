import sqlite3
import time

from app import memory


def test_add_then_recent_oldest_to_newest(memdb):
    now = time.time()
    memory.add(1, "first", ts=now - 10)
    memory.add(1, "second", ts=now - 5)
    memory.add(1, "third", ts=now)
    assert memory.recent(1) == ["first", "second", "third"]


def test_per_chat_isolation(memdb):
    now = time.time()
    memory.add(1, "chat one", ts=now)
    memory.add(2, "chat two", ts=now)
    assert memory.recent(1) == ["chat one"]
    assert memory.recent(2) == ["chat two"]


def test_window_excludes_old(memdb):
    now = time.time()
    memory.add(1, "stale", ts=now - 25 * 3600)
    memory.add(1, "fresh", ts=now - 1 * 3600)
    assert memory.recent(1) == ["fresh"]


def test_recent_prunes_expired_rows(memdb):
    now = time.time()
    memory.add(1, "stale", ts=now - 25 * 3600)
    memory.recent(1)  # 触发清理
    # 直接查库确认旧行已被删除
    conn = sqlite3.connect(memdb.DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
    conn.close()
    assert count == 0


def test_caps_at_max_messages(memdb, monkeypatch):
    monkeypatch.setattr(memdb, "MEMORY_MAX_MESSAGES", 3)
    now = time.time()
    for i in range(5):
        memory.add(1, f"m{i}", ts=now - (5 - i))  # m0 最旧 … m4 最新
    # 只保留最近 3 条，按时间顺序返回
    assert memory.recent(1) == ["m2", "m3", "m4"]


def test_trims_long_text(memdb, monkeypatch):
    monkeypatch.setattr(memdb, "MEMORY_MAX_CHARS", 10)
    memory.add(1, "x" * 50, ts=time.time())
    assert memory.recent(1) == ["x" * 10]


def test_skips_empty_text(memdb):
    memory.add(1, "   ", ts=time.time())
    memory.add(1, "", ts=time.time())
    assert memory.recent(1) == []


def test_speaker_prefix_when_present(memdb):
    now = time.time()
    memory.add(1, "你好", ts=now - 1, speaker="张三")
    memory.add(1, "无名", ts=now)  # 无 speaker
    assert memory.recent(1) == ["张三：你好", "无名"]


def test_recent_returns_empty_on_db_error(memdb, monkeypatch):
    # 指向一个不存在的目录，sqlite3.connect 会报 "unable to open database file"
    monkeypatch.setattr(memdb, "DB_PATH", "/nonexistent-dir/does/not/exist.db")
    assert memory.recent(1) == []


def test_add_does_not_raise_on_db_error(memdb, monkeypatch):
    monkeypatch.setattr(memdb, "DB_PATH", "/nonexistent-dir/does/not/exist.db")
    memory.add(1, "hi", ts=time.time())  # 不应抛异常
