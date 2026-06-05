from types import SimpleNamespace

import pytest

from app import asr, config


# ---- 上下文偏置：把热词地名拼成给 Qwen 的提示 ----

def test_build_context_includes_hotwords():
    ctx = asr._build_context(["Ashfield", "Burwood"])
    assert "Ashfield" in ctx and "Burwood" in ctx


def test_build_context_empty_when_no_hotwords():
    assert asr._build_context([]) == ""


# ---- 从 MultiModalConversation 响应里抽文字（dict / 对象 / 字符串都要兼容）----

def _resp(content):
    msg = {"message": {"content": content}}
    return SimpleNamespace(status_code=200, output={"choices": [msg]})


def test_extract_text_list_of_dicts():
    assert asr._extract_text(_resp([{"text": "侬好"}])) == "侬好"


def test_extract_text_multiple_parts_joined():
    assert asr._extract_text(_resp([{"text": "abc"}, {"text": "def"}])) == "abcdef"


def test_extract_text_plain_string():
    assert asr._extract_text(_resp("hello")) == "hello"


def test_extract_text_no_choices():
    assert asr._extract_text(SimpleNamespace(output={"choices": []})) == ""


# ---- 切片计划：短音频单片，长音频切成多片且完整覆盖 ----

def test_segment_plan_short_single_chunk():
    assert asr._segment_plan(120.0, 170.0) == [(0.0, 120.0)]


def test_segment_plan_long_splits_and_covers():
    plan = asr._segment_plan(400.0, 170.0)
    assert len(plan) == 3
    assert plan[0][0] == 0.0
    # 各片相加 == 总时长，无缺口无重叠
    assert sum(length for _, length in plan) == pytest.approx(400.0)
    # 每片都不超过上限
    assert all(length <= 170.0 for _, length in plan)


# ---- get_asr() 按 provider 选实现 ----

def test_get_asr_qwen(monkeypatch):
    monkeypatch.setattr(config, "ASR_PROVIDER", "qwen")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "sk-test")
    assert isinstance(asr.get_asr(), asr.QwenASR)


def test_get_asr_unknown(monkeypatch):
    monkeypatch.setattr(config, "ASR_PROVIDER", "nope")
    with pytest.raises(RuntimeError):
        asr.get_asr()


# ---- 单次（短音频）transcribe：不切片，直接把 URL 喂给 Qwen ----

def test_transcribe_single_call(monkeypatch):
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setattr(config, "FUNASR_HOTWORDS", ["Ashfield"])
    monkeypatch.setattr(config, "QWEN_ASR_MAX_CHUNK_SECONDS", 170.0)
    # 短音频 → 不切片
    monkeypatch.setattr(asr, "_probe_duration", lambda audio: 10.0)

    captured = {}

    def fake_call(*, model, messages, asr_options):
        captured["model"] = model
        captured["messages"] = messages
        captured["asr_options"] = asr_options
        return _resp([{"text": "明朝去 Ashfield"}])

    import dashscope
    monkeypatch.setattr(dashscope.MultiModalConversation, "call", staticmethod(fake_call))

    out = asr.QwenASR().transcribe(audio_url="https://example.com/a.ogg")
    assert out == "明朝去 Ashfield"
    # 用户消息带 audio，URL 原样传递
    user_msg = captured["messages"][-1]
    assert user_msg["content"][0]["audio"] == "https://example.com/a.ogg"
    # 系统消息带上了热词偏置
    assert any("Ashfield" in (m["content"][0].get("text", "")) for m in captured["messages"] if m["role"] == "system")


def test_transcribe_raises_on_error_status(monkeypatch):
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setattr(config, "FUNASR_HOTWORDS", [])
    monkeypatch.setattr(asr, "_probe_duration", lambda audio: 10.0)

    def fake_call(**kwargs):
        return SimpleNamespace(status_code=400, message="bad request", output=None)

    import dashscope
    monkeypatch.setattr(dashscope.MultiModalConversation, "call", staticmethod(fake_call))

    with pytest.raises(RuntimeError, match="Qwen-ASR"):
        asr.QwenASR().transcribe(audio_url="https://example.com/a.ogg")
