from types import SimpleNamespace

from app import agent


def test_trigger_and_strip():
    assert agent.is_agent_trigger("你好 summary")
    assert agent.is_agent_trigger("侬好，明天下雨吗")
    assert not agent.is_agent_trigger("今天天气不错")
    assert agent.strip_greeting("你好，明天 Homebush 下雨吗") == "明天 Homebush 下雨吗"


def _msg(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tc(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class _ScriptedCompletions:
    """按预设脚本逐次返回不同的回复，并记录每次收到的 messages。"""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        msg = self._replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _install(monkeypatch, replies):
    comps = _ScriptedCompletions(replies)
    monkeypatch.setattr(agent, "_client", SimpleNamespace(chat=SimpleNamespace(completions=comps)))
    return comps


def test_direct_answer_without_tools(monkeypatch):
    comps = _install(monkeypatch, [_msg(content="直接回答")])

    out = agent.respond("总结一下", context=["张三：去了 Ashfield"], requester="李四")

    assert out == "直接回答"
    # 单轮即结束，只调用一次模型
    assert len(comps.calls) == 1
    # 工具 schema 一并发出
    assert comps.calls[0]["tools"] == agent._TOOLS
    # 请求者写进 system
    assert "李四" in comps.calls[0]["messages"][0]["content"]


def test_tool_call_loop_feeds_result_back(monkeypatch):
    monkeypatch.setattr(agent.weather, "get_weather", lambda loc, days=1: f"WEATHER[{loc},{days}]")
    comps = _install(monkeypatch, [
        _msg(tool_calls=[_tc("c1", "get_weather", '{"location": "Homebush", "days": 2}')]),
        _msg(content="明天多云，带把伞"),
    ])

    out = agent.respond("你好 明天 Homebush 下雨吗")

    assert out == "明天多云，带把伞"
    # 两轮：先要工具，再给最终回复
    assert len(comps.calls) == 2
    # 第二轮的 messages 里要带上 assistant(tool_calls) 和 tool 结果
    second = comps.calls[1]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": "WEATHER[Homebush,2]"}


def test_unknown_tool_does_not_crash(monkeypatch):
    comps = _install(monkeypatch, [
        _msg(tool_calls=[_tc("c1", "no_such_tool", "{}")]),
        _msg(content="兜底回复"),
    ])

    out = agent.respond("随便")

    assert out == "兜底回复"
    assert "未知工具" in comps.calls[1]["messages"][-1]["content"]
