# One-day DeepSeek memory — design

Roadmap #1 from `README.md`: give the polish step short-term context. Keep the
last ~24h of group messages, auto-expire older ones, and feed them to DeepSeek
so polished results reference earlier messages and stay consistent in wording
(names, places, terminology).

## Decisions

- **Scope:** per group (whole chat). Context key is `chat_id`; everyone's
  recent messages form one shared context, regardless of who spoke.
- **What's stored / fed back:** the *polished* result of each voice message,
  plus *plain text messages* people type in the group. Both feed the polish
  step. The bot's own replies and slash-commands are never stored.
- **Speaker tagging:** each stored line records who spoke (sender's display
  name), and the DeepSeek context block prefixes each line with it
  (`张三：…`). This helps pronoun/context resolution and sets up roadmap #2.
  It only affects the *context* fed to DeepSeek — the bot's reply is **not**
  prefixed (that output-side change stays in roadmap #2).
- **Window:** sliding 24h **AND** at most the last 50 messages per chat.
- **Per-message char cap:** each stored text is trimmed to 1000 chars so a
  single long paste can't dominate the prompt.
- **Timestamp:** the Telegram message time (`msg.date`), not wall-clock at
  insert — voice polishing can lag, and we want correct chronological order
  when text and voice messages interleave.
- **Storage:** SQLite at `config.DB_PATH` (the `/data` named volume in Docker).
  Survives restarts, which a 24h window requires. Matches the README plan.

## Architecture

One new module `app/memory.py` — a thin SQLite layer. Single table:

```sql
CREATE TABLE IF NOT EXISTS memory (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    ts      REAL    NOT NULL,   -- epoch seconds, from msg.date
    speaker TEXT    NOT NULL,   -- sender display name ('' if unknown)
    text    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_chat_ts ON memory(chat_id, ts);
```

Connections are opened per call (safe across `asyncio.to_thread` worker
threads — no shared connection object). Schema is created at startup.

### Public interface (`app/memory.py`)

- `init() -> None` — create table + index if missing. Called once at startup.
- `add(chat_id: int, text: str, *, ts: float, speaker: str = "") -> None` —
  trim `text` to `MEMORY_MAX_CHARS`, skip if empty after trim, insert one row
  with `speaker`.
- `recent(chat_id: int) -> list[str]` — return prior lines for the chat,
  **oldest → newest**, within `MEMORY_WINDOW_HOURS`, capped at the most recent
  `MEMORY_MAX_MESSAGES`. Each line is formatted `f"{speaker}：{text}"` when a
  speaker is known, else just `text`. Prunes expired rows for that chat as a
  side effect.

All three are best-effort: exceptions are caught and logged inside the module,
returning a safe default (`recent` → `[]`, `add`/`init` → no-op). Memory can
never break transcription.

## Data flow (in `bot.py`)

Only active when `config.POLISH_ENABLED and config.MEMORY_ENABLED`.

A small helper `_speaker(msg) -> str` derives the sender's display name from
`msg.from_user` — `full_name` if present, else `username`, else `""`.

**Voice / audio message (`on_voice`)** — unchanged up to the polish step:
1. ASR → `transcript`.
2. `context = await asyncio.to_thread(memory.recent, chat.id)`.
3. `text = await _polish(transcript, context)`.
4. After the reply text is finalized:
   `await asyncio.to_thread(memory.add, chat.id, text, ts=msg.date.timestamp(), speaker=_speaker(msg))`.

**Text message (new `on_text` handler)** — `filters.TEXT & ~filters.COMMAND`:
1. Respect `_allowed(chat.id)`; return early if memory/polish disabled.
2. `await asyncio.to_thread(memory.add, chat.id, msg.text, ts=msg.date.timestamp(), speaker=_speaker(msg))`.
3. No reply.

Handler registration in `main()`:
```python
app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
```
`memory.init()` is called in `main()` before `run_polling`.

## DeepSeek integration (`deepseek_client.py`)

`polish(transcript, context=None)` gains an optional `context: list[str]`.

When `context` is non-empty, prepend a context block. The existing `_SYSTEM`
prompt stays; we add a second system message:

> 以下是该群最近的对话内容（已整理，按时间先后排列），仅供参考，帮助你保持人名、
> 地名、专有名词和用词的一致；不要把这些内容混进本次输出。
>
> {chronological lines joined by "\n"}

Each line already carries its speaker prefix (`张三：…`) from `memory.recent`.
The new transcript remains the sole user message. When `context` is empty or
`None`, behaviour is identical to today.

`_polish(transcript, context)` in `bot.py` passes the context through to
`deepseek_client.polish`; its retry/fallback logic is otherwise unchanged.

## Config additions (`config.py` + `.env.example`)

| Var | Default | Meaning |
|-----|---------|---------|
| `MEMORY_ENABLED` | `true` | Master switch; no-op when `POLISH_ENABLED=false`. |
| `MEMORY_WINDOW_HOURS` | `24` | Sliding expiry window. |
| `MEMORY_MAX_MESSAGES` | `50` | Max messages fed as context per chat. |
| `MEMORY_MAX_CHARS` | `1000` | Per-message stored-text cap. |

`DB_PATH` already exists and is reused.

## Error handling

Memory is strictly best-effort and isolated:
- `recent` failure → `[]`, polish runs context-free.
- `add` failure → logged, reply still sent.
- `init` failure → logged; subsequent ops fail soft.

No memory path raises into `on_voice`/`on_text`. Transcription behaviour with
memory failing equals today's behaviour.

## Testing (TDD)

No test framework exists yet — add `pytest` to `requirements.txt`.

`tests/test_memory.py` (temp-file SQLite via `DB_PATH` override / fixture):
- `add` then `recent` returns text oldest→newest.
- Rows older than `MEMORY_WINDOW_HOURS` are excluded and pruned.
- Only the most recent `MEMORY_MAX_MESSAGES` are returned when more exist.
- Per-chat isolation: chat A never sees chat B's messages.
- Text longer than `MEMORY_MAX_CHARS` is trimmed; empty/whitespace skipped.
- A line stored with a `speaker` comes back prefixed `f"{speaker}：{text}"`;
  with no speaker it comes back as bare `text`.
- `recent` on a DB error returns `[]` (no raise).

`tests/test_deepseek_polish.py` (stubbed OpenAI client):
- With non-empty `context`, the context block is present and lines appear in
  chronological order in the messages sent.
- With empty/`None` context, messages match today's two-message shape.

## Out of scope

- Prefixing the **bot's reply** with the speaker name (roadmap #2). This spec
  only tags speakers in the context fed to DeepSeek, not in the output.
- Summaries or agent commands (roadmap #3).
- De-duplication of repeated `file_id`s.
