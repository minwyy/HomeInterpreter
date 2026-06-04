# One-day DeepSeek Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the DeepSeek polish step a per-group 24h memory of recent messages (typed text + polished voice transcripts, tagged by speaker) so it keeps names, places, and wording consistent.

**Architecture:** A new best-effort SQLite module `app/memory.py` (table at `config.DB_PATH`) stores recent messages per `chat_id`. `bot.py` records every text message and every polished voice result, and fetches the recent window to pass into `deepseek_client.polish(...)`, which prepends a speaker-tagged context block. Memory failures degrade silently and never break transcription.

**Tech Stack:** Python 3, `sqlite3` (stdlib), python-telegram-bot, OpenAI SDK (DeepSeek), `pytest` (new test dep).

**Spec:** `docs/superpowers/specs/2026-06-04-one-day-deepseek-memory-design.md`

---

## File Structure

- **Create** `app/memory.py` — SQLite store: `init()`, `add()`, `recent()`. Reads all config at call-time (so tests can monkeypatch).
- **Modify** `app/config.py` — add `MEMORY_ENABLED`, `MEMORY_WINDOW_HOURS`, `MEMORY_MAX_MESSAGES`, `MEMORY_MAX_CHARS`.
- **Modify** `app/deepseek_client.py` — `polish(transcript, context=None)` prepends a speaker-tagged context block.
- **Modify** `app/bot.py` — `_speaker()` helper, `_polish()` gains `context`, `on_voice` fetches/records memory, new `on_text` handler, `main()` calls `memory.init()` and registers the text handler.
- **Create** `tests/conftest.py` — seeds dummy env before `app.*` import; `memdb` fixture pointing `DB_PATH` at a temp file.
- **Create** `tests/test_config.py`, `tests/test_memory.py`, `tests/test_deepseek.py`, `tests/test_bot.py`.
- **Modify** `requirements.txt` — add `pytest`.
- **Modify** `.env.example` — document the four `MEMORY_*` vars.
- **Modify** `README.md` — mark roadmap #1 done; note SQLite memory.

---

## Task 1: Test scaffolding + config + env vars

**Files:**
- Modify: `requirements.txt`
- Modify: `app/config.py`
- Modify: `.env.example`
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Add pytest to requirements and install**

Append to `requirements.txt`:
```
pytest>=8.0
```
Run: `./venv/bin/pip install -r requirements.txt`
Expected: pytest installs successfully.

- [ ] **Step 2: Add the memory config vars**

In `app/config.py`, after the DeepSeek block (after the `DEEPSEEK_BASE_URL` line, before the validation `if` block), add:
```python
# 一天记忆(roadmap #1)：把群里最近消息当上下文喂给 DeepSeek，保持人名/地名/用词一致。
# 只在 POLISH_ENABLED=true 时才有意义。
MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "true").lower() == "true"
MEMORY_WINDOW_HOURS = float(os.getenv("MEMORY_WINDOW_HOURS", "24"))
MEMORY_MAX_MESSAGES = int(os.getenv("MEMORY_MAX_MESSAGES", "50"))
MEMORY_MAX_CHARS = int(os.getenv("MEMORY_MAX_CHARS", "1000"))
```

- [ ] **Step 3: Document the vars in `.env.example`**

Append to `.env.example`:
```
# ---- 一天记忆(roadmap #1，只在 POLISH_ENABLED=true 时生效) ----
# 把群里最近的消息(文字 + 已整理的语音)当上下文喂给 DeepSeek，保持用词一致。
MEMORY_ENABLED=true
MEMORY_WINDOW_HOURS=24
MEMORY_MAX_MESSAGES=50
MEMORY_MAX_CHARS=1000
```

- [ ] **Step 4: Create `tests/conftest.py`**

`app/config.py` validates required env at import, so seed dummy values BEFORE any `app.*` import (pytest imports conftest first):
```python
"""测试夹具：在导入 app.* 前塞入假环境变量，并提供临时 SQLite 路径。"""
import os

# 必须在 import app.config 之前设置(config 在导入时校验必填项)。
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("DASHSCOPE_API_KEY", "sk-test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("POLISH_ENABLED", "true")

import pytest

from app import config


@pytest.fixture
def memdb(tmp_path, monkeypatch):
    """把 DB_PATH 指到临时文件；memory.py 在调用时才读 config.DB_PATH，故 monkeypatch 生效。"""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    return config
```

- [ ] **Step 5: Write the config smoke test**

Create `tests/test_config.py`:
```python
from app import config


def test_memory_defaults_present():
    assert config.MEMORY_ENABLED is True
    assert config.MEMORY_WINDOW_HOURS == 24
    assert config.MEMORY_MAX_MESSAGES == 50
    assert config.MEMORY_MAX_CHARS == 1000
```

- [ ] **Step 6: Run the test**

Run: `./venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (1 passed).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt app/config.py .env.example tests/conftest.py tests/test_config.py
git commit -m "Add memory config vars and pytest test scaffolding"
```

---

## Task 2: `app/memory.py` core — add/recent, ordering, isolation, expiry, cap

**Files:**
- Create: `app/memory.py`
- Create: `tests/test_memory.py`

- [ ] **Step 1: Write the failing test — add then recent, oldest→newest, per-chat isolation**

Create `tests/test_memory.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_memory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.memory'`.

- [ ] **Step 3: Create `app/memory.py` (no window/cap yet)**

```python
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
    conn = _connect()
    with conn:
        rows = conn.execute(
            "SELECT text FROM memory WHERE chat_id = ? ORDER BY ts ASC, id ASC",
            (chat_id,),
        ).fetchall()
    conn.close()
    return [r[0] for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_memory.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the failing test — 24h window excludes & prunes old rows**

Append to `tests/test_memory.py`:
```python
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
    import sqlite3

    conn = sqlite3.connect(memdb.DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
    conn.close()
    assert count == 0
```

- [ ] **Step 6: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_memory.py -v`
Expected: FAIL — `test_window_excludes_old` returns `["stale", "fresh"]`; `test_recent_prunes_expired_rows` finds count 1.

- [ ] **Step 7: Add the window filter + prune to `recent`**

Replace the `recent` function in `app/memory.py` with:
```python
def recent(chat_id: int) -> list[str]:
    cutoff = time.time() - config.MEMORY_WINDOW_HOURS * 3600
    conn = _connect()
    with conn:
        conn.execute("DELETE FROM memory WHERE ts < ?", (cutoff,))  # 顺手清过期
        rows = conn.execute(
            "SELECT text FROM memory WHERE chat_id = ? AND ts >= ? "
            "ORDER BY ts ASC, id ASC",
            (chat_id, cutoff),
        ).fetchall()
    conn.close()
    return [r[0] for r in rows]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_memory.py -v`
Expected: PASS (4 passed).

- [ ] **Step 9: Write the failing test — cap at MEMORY_MAX_MESSAGES (most recent N)**

Append to `tests/test_memory.py`:
```python
def test_caps_at_max_messages(memdb, monkeypatch):
    monkeypatch.setattr(memdb, "MEMORY_MAX_MESSAGES", 3)
    now = time.time()
    for i in range(5):
        memory.add(1, f"m{i}", ts=now - (5 - i))  # m0 最旧 … m4 最新
    # 只保留最近 3 条，按时间顺序返回
    assert memory.recent(1) == ["m2", "m3", "m4"]
```

- [ ] **Step 10: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_memory.py::test_caps_at_max_messages -v`
Expected: FAIL — returns all 5 (`["m0",...,"m4"]`).

- [ ] **Step 11: Add the LIMIT + reverse to `recent`**

Replace the `recent` function in `app/memory.py` with:
```python
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
```

- [ ] **Step 12: Run all memory tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_memory.py -v`
Expected: PASS (5 passed).

- [ ] **Step 13: Commit**

```bash
git add app/memory.py tests/test_memory.py
git commit -m "Add SQLite memory store: add/recent with 24h window and max-N cap"
```

---

## Task 3: `app/memory.py` — char trim, empty skip, speaker prefix

**Files:**
- Modify: `app/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Write the failing test — trim long text, skip empty**

Append to `tests/test_memory.py`:
```python
def test_trims_long_text(memdb, monkeypatch):
    monkeypatch.setattr(memdb, "MEMORY_MAX_CHARS", 10)
    memory.add(1, "x" * 50, ts=time.time())
    assert memory.recent(1) == ["x" * 10]


def test_skips_empty_text(memdb):
    memory.add(1, "   ", ts=time.time())
    memory.add(1, "", ts=time.time())
    assert memory.recent(1) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_memory.py::test_trims_long_text tests/test_memory.py::test_skips_empty_text -v`
Expected: FAIL — full 50 chars stored; blank rows stored.

- [ ] **Step 3: Add trim + skip to `add`**

Replace the `add` function in `app/memory.py` with:
```python
def add(chat_id: int, text: str, *, ts: float, speaker: str = "") -> None:
    text = (text or "").strip()[: config.MEMORY_MAX_CHARS]
    if not text:
        return  # 空消息不存
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT INTO memory (chat_id, ts, speaker, text) VALUES (?, ?, ?, ?)",
            (chat_id, ts, speaker or "", text),
        )
    conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_memory.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Write the failing test — speaker prefix**

Append to `tests/test_memory.py`:
```python
def test_speaker_prefix_when_present(memdb):
    now = time.time()
    memory.add(1, "你好", ts=now - 1, speaker="张三")
    memory.add(1, "无名", ts=now)  # 无 speaker
    assert memory.recent(1) == ["张三：你好", "无名"]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_memory.py::test_speaker_prefix_when_present -v`
Expected: FAIL — returns `["你好", "无名"]` (no prefix).

- [ ] **Step 7: Add speaker formatting to `recent`**

Replace the final `return` line of `recent` in `app/memory.py`:
```python
    return [r[1] for r in rows]
```
with:
```python
    return [f"{sp}：{tx}" if sp else tx for sp, tx in rows]
```

- [ ] **Step 8: Run all memory tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_memory.py -v`
Expected: PASS (8 passed).

- [ ] **Step 9: Commit**

```bash
git add app/memory.py tests/test_memory.py
git commit -m "Add char-cap, empty-skip, and speaker prefix to memory store"
```

---

## Task 4: `app/memory.py` — best-effort error handling

**Files:**
- Modify: `app/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Write the failing test — DB error degrades, never raises**

Append to `tests/test_memory.py`:
```python
def test_recent_returns_empty_on_db_error(memdb, monkeypatch):
    # 指向一个不存在的目录，sqlite3.connect 会报 "unable to open database file"
    monkeypatch.setattr(memdb, "DB_PATH", "/nonexistent-dir/does/not/exist.db")
    assert memory.recent(1) == []


def test_add_does_not_raise_on_db_error(memdb, monkeypatch):
    monkeypatch.setattr(memdb, "DB_PATH", "/nonexistent-dir/does/not/exist.db")
    memory.add(1, "hi", ts=time.time())  # 不应抛异常
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_memory.py::test_recent_returns_empty_on_db_error tests/test_memory.py::test_add_does_not_raise_on_db_error -v`
Expected: FAIL — both raise `sqlite3.OperationalError`.

- [ ] **Step 3: Wrap `init`, `add`, `recent` in try/except**

Replace `init`, `add`, and `recent` in `app/memory.py` with these final versions:
```python
def init() -> None:
    """启动时建表。失败只记日志(best-effort)。"""
    try:
        _connect().close()
    except Exception:  # noqa: BLE001
        logger.exception("memory.init 失败")


def add(chat_id: int, text: str, *, ts: float, speaker: str = "") -> None:
    text = (text or "").strip()[: config.MEMORY_MAX_CHARS]
    if not text:
        return  # 空消息不存
    try:
        conn = _connect()
        with conn:
            conn.execute(
                "INSERT INTO memory (chat_id, ts, speaker, text) VALUES (?, ?, ?, ?)",
                (chat_id, ts, speaker or "", text),
            )
        conn.close()
    except Exception:  # noqa: BLE001
        logger.exception("memory.add 失败")


def recent(chat_id: int) -> list[str]:
    cutoff = time.time() - config.MEMORY_WINDOW_HOURS * 3600
    try:
        conn = _connect()
        with conn:
            conn.execute("DELETE FROM memory WHERE ts < ?", (cutoff,))  # 顺手清过期
            rows = conn.execute(
                "SELECT speaker, text FROM memory WHERE chat_id = ? AND ts >= ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (chat_id, cutoff, config.MEMORY_MAX_MESSAGES),
            ).fetchall()
        conn.close()
    except Exception:  # noqa: BLE001
        logger.exception("memory.recent 失败")
        return []
    rows.reverse()  # 取最近 N 条后，倒回成 旧→新
    return [f"{sp}：{tx}" if sp else tx for sp, tx in rows]
```

- [ ] **Step 4: Run all memory tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_memory.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add app/memory.py tests/test_memory.py
git commit -m "Make memory store best-effort: swallow DB errors and degrade"
```

---

## Task 5: `app/deepseek_client.py` — context-aware polish

**Files:**
- Modify: `app/deepseek_client.py`
- Create: `tests/test_deepseek.py`

- [ ] **Step 1: Write the failing test — context block present and chronological**

Create `tests/test_deepseek.py`:
```python
from types import SimpleNamespace

from app import deepseek_client


class _FakeCompletions:
    def __init__(self):
        self.captured = None

    def create(self, **kwargs):
        self.captured = kwargs
        msg = SimpleNamespace(content="整理后的文字")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_polish_with_context_adds_chronological_block(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(deepseek_client, "_client", fake)

    out = deepseek_client.polish("今天去哪", context=["张三：昨天去了 Ashfield", "李四：好的"])

    assert out == "整理后的文字"
    messages = fake.chat.completions.create.__self__.captured["messages"]
    # 角色顺序：system(基础) → system(上下文) → user(本次转写)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "system"
    assert "张三：昨天去了 Ashfield" in messages[1]["content"]
    # 时间先后：张三这行在李四之前
    assert messages[1]["content"].index("张三") < messages[1]["content"].index("李四")
    assert messages[-1] == {"role": "user", "content": "今天去哪"}


def test_polish_without_context_keeps_two_messages(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(deepseek_client, "_client", fake)

    deepseek_client.polish("今天去哪")

    messages = fake.chat.completions.create.__self__.captured["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "今天去哪"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_deepseek.py -v`
Expected: FAIL — `polish()` takes no `context` argument (`TypeError`).

- [ ] **Step 3: Add the context parameter and block**

In `app/deepseek_client.py`, after the `_SYSTEM` string definition, add:
```python
_CONTEXT_PREFIX = (
    "以下是该群最近的对话内容（已整理，按时间先后排列），仅供参考，帮助你保持人名、"
    "地名、专有名词和用词的一致；不要把这些内容混进本次输出。\n\n"
)
```
Then replace the `polish` function with:
```python
def polish(transcript: str, context: list[str] | None = None) -> str:
    if not transcript:
        return ""
    messages = [{"role": "system", "content": _SYSTEM}]
    if context:
        messages.append(
            {"role": "system", "content": _CONTEXT_PREFIX + "\n".join(context)}
        )
    messages.append({"role": "user", "content": transcript})
    resp = _client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=600,
    )
    return resp.choices[0].message.content.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_deepseek.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/deepseek_client.py tests/test_deepseek.py
git commit -m "Add optional speaker-tagged context block to DeepSeek polish"
```

---

## Task 6: `app/bot.py` — wire memory into handlers

**Files:**
- Modify: `app/bot.py`
- Create: `tests/test_bot.py`

- [ ] **Step 1: Write the failing test — `_speaker` and `_polish` forwarding**

Create `tests/test_bot.py`:
```python
import asyncio
from types import SimpleNamespace

from app import bot, deepseek_client


def test_speaker_prefers_full_name():
    msg = SimpleNamespace(from_user=SimpleNamespace(full_name="张三", username="z3"))
    assert bot._speaker(msg) == "张三"


def test_speaker_falls_back_to_username():
    msg = SimpleNamespace(from_user=SimpleNamespace(full_name="", username="z3"))
    assert bot._speaker(msg) == "z3"


def test_speaker_empty_when_no_user():
    assert bot._speaker(SimpleNamespace(from_user=None)) == ""


def test_polish_forwards_context(monkeypatch):
    captured = {}

    def fake_polish(transcript, context=None):
        captured["transcript"] = transcript
        captured["context"] = context
        return "ok"

    monkeypatch.setattr(deepseek_client, "polish", fake_polish)
    out = asyncio.run(bot._polish("你好", ["张三：昨天"]))
    assert out == "ok"
    assert captured == {"transcript": "你好", "context": ["张三：昨天"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_bot.py -v`
Expected: FAIL — `bot._speaker` does not exist; `_polish` takes no `context`.

- [ ] **Step 3: Add `_speaker` helper and update `_polish`**

In `app/bot.py`, add the import to the existing `from . import` line so it reads:
```python
from . import config, asr, deepseek_client, memory
```
Add this helper after `_allowed`:
```python
def _speaker(msg) -> str:
    """取发送者显示名：优先 full_name，退而 username，再退空串。"""
    u = getattr(msg, "from_user", None)
    if not u:
        return ""
    return u.full_name or u.username or ""
```
Replace the `_polish` signature and its single `deepseek_client.polish` call:
```python
async def _polish(transcript: str, context: list[str] | None = None) -> str:
    """整理转写文字：空结果或出错时重试一次；最终仍失败/为空则回退到原始转写。"""
    for attempt in range(2):  # 初次 + 1 次重试
        try:
            text = await asyncio.to_thread(deepseek_client.polish, transcript, context)
        except Exception as e:  # noqa: BLE001
            logger.warning("DeepSeek 第%d次失败: %s", attempt + 1, e)
            text = ""
        if text:
            return text
        if attempt == 0:
            logger.info("DeepSeek 返回空/出错，重试一次…")
            await asyncio.sleep(1.0)
    logger.info("DeepSeek 整理未成功，回退到原始转写")
    return transcript
```

- [ ] **Step 4: Run the bot tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_bot.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Wire memory into `on_voice`**

In `app/bot.py`, replace the polish/reply block inside `on_voice` (currently):
```python
        if config.POLISH_ENABLED:
            logger.info("DeepSeek 整理中…")
            text = await _polish(transcript)
            logger.info("DeepSeek 结果: %s", text)
        else:
            text = transcript

        await placeholder.edit_text(f"🎙 {text}")
```
with:
```python
        if config.POLISH_ENABLED:
            context = (
                await asyncio.to_thread(memory.recent, chat.id)
                if config.MEMORY_ENABLED
                else []
            )
            logger.info("DeepSeek 整理中…（上下文 %d 条）", len(context))
            text = await _polish(transcript, context)
            logger.info("DeepSeek 结果: %s", text)
        else:
            text = transcript

        await placeholder.edit_text(f"🎙 {text}")

        if config.POLISH_ENABLED and config.MEMORY_ENABLED:
            await asyncio.to_thread(
                memory.add, chat.id, text, ts=msg.date.timestamp(), speaker=_speaker(msg)
            )
```

- [ ] **Step 6: Add the `on_text` handler**

In `app/bot.py`, add after `on_voice`:
```python
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """把群里的文字消息也记进一天记忆，供后续整理时当上下文；不回复。"""
    if not (config.POLISH_ENABLED and config.MEMORY_ENABLED):
        return
    msg = update.effective_message
    chat = update.effective_chat
    if not _allowed(chat.id) or not msg or not msg.text:
        return
    await asyncio.to_thread(
        memory.add, chat.id, msg.text, ts=msg.date.timestamp(), speaker=_speaker(msg)
    )
```

- [ ] **Step 7: Register the handler and init memory in `main`**

In `app/bot.py`, replace the body of `main()` up to `run_polling` with:
```python
def main() -> None:
    memory.init()
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    logger.info("bot 启动，长轮询中…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
```

- [ ] **Step 8: Run the full test suite + import-check the bot module**

Run: `./venv/bin/python -m pytest tests/ -v`
Expected: PASS (all tests green).
Run: `./venv/bin/python -c "import app.bot"`
Expected: no error (module imports cleanly with dummy env from a real `.env`).

- [ ] **Step 9: Commit**

```bash
git add app/bot.py tests/test_bot.py
git commit -m "Wire one-day memory into voice + text handlers"
```

---

## Task 7: Documentation — README + spec wording

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-06-04-one-day-deepseek-memory-design.md`

- [ ] **Step 1: Mark roadmap #1 done in README**

In `README.md`, replace the roadmap #1 line:
```
1. **One-day DeepSeek memory** — give the polish step short-term context: keep the last ~24h of transcripts per group (or per person), auto-expire older ones, so results can reference earlier messages and stay consistent in wording.
```
with:
```
1. ✅ **One-day DeepSeek memory** *(done)* — the polish step gets per-group short-term context: the last 24h of group messages (typed text + polished voice transcripts, tagged by speaker, capped at 50 / 1000 chars each) are stored in SQLite at `DB_PATH` and fed to DeepSeek so results reference earlier messages and stay consistent in wording. Tune via `MEMORY_*` env vars. See `app/memory.py`.
```

- [ ] **Step 2: Update the file-structure block in README**

In `README.md`, inside the `app/` tree block, add a line after the `deepseek_client.py` entry:
```
└── memory.py          一天记忆：SQLite 存近 24h 群消息，喂给 DeepSeek 当上下文
```
(and fix the box-drawing of the `deepseek_client.py` line from `└──` to `├──` so `memory.py` becomes the last entry.)

- [ ] **Step 3: Update the "后续可做" note about roadmap #1**

In `README.md`, in the `## 后续可做` section, replace:
```
- 状态(如 roadmap #1 的一天记忆)用 SQLite 落到 `/data`(named volume)。热词目前在 `.env` 的 `FUNASR_HOTWORDS`(经 `manage_vocab.py` 推到阿里云,不在本地 state);#5 才考虑搬到文件/DB。
```
with:
```
- 一天记忆(roadmap #1)已落地：SQLite 写在 `DB_PATH`(容器里挂 `/data` named volume)。热词目前在 `.env` 的 `FUNASR_HOTWORDS`(经 `manage_vocab.py` 推到阿里云,不在本地 state);#5 才考虑搬到文件/DB。
```

- [ ] **Step 4: Sync the spec's prune wording**

In `docs/superpowers/specs/2026-06-04-one-day-deepseek-memory-design.md`, in the `recent` bullet under "Public interface", replace `Prunes expired rows for that chat as a side effect.` with `Prunes expired rows (all chats) as a side effect.` to match the implementation's global `DELETE WHERE ts < cutoff`.

- [ ] **Step 5: Final full-suite run**

Run: `./venv/bin/python -m pytest tests/ -v`
Expected: PASS (all tests green).

- [ ] **Step 6: Commit**

```bash
git add README.md docs/superpowers/specs/2026-06-04-one-day-deepseek-memory-design.md
git commit -m "Mark roadmap #1 (one-day memory) done; sync docs"
```

---

## Manual Verification (after all tasks)

The handler bodies (`on_voice`/`on_text` Telegram plumbing) are not unit-tested. After implementation, do a live smoke test:

1. `cp .env.example .env`, fill real tokens, set `POLISH_ENABLED=true`.
2. `./venv/bin/python -m app.bot` (or `docker compose up --build`).
3. In an allowed group: send a text message naming a place (e.g. "明天去 Ashfield"), then send a Shanghainese voice message that refers back to it.
4. Confirm the polished reply stays consistent with the earlier typed message (same place name/wording).
5. Confirm `state.db` (or `/data/state.db`) contains rows: `sqlite3 state.db "SELECT chat_id, speaker, text FROM memory;"`.
6. Restart the bot; confirm context from before the restart still influences the next polish (persistence).
