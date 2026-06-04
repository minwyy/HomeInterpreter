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
