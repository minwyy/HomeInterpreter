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
    messages = fake.chat.completions.captured["messages"]
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

    messages = fake.chat.completions.captured["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "今天去哪"}
