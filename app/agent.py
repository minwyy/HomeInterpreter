"""Agent mode: voice/text starting with '你好'/'侬好' is sent to DeepSeek as a
free-form request rather than a transcription to polish.  DeepSeek decides
what to do (summarise, translate, answer a question, etc.) based on the
request and the recent group conversation context.

🔁 Function-calling loop (roadmap #6): the model is offered tools (currently
just `get_weather`). Each round we send the conversation + tool schemas; if the
model replies with tool calls we run them, append the results, and loop again —
until the model returns a plain answer (or we hit the round cap).
"""
import json
import logging
import re

from openai import OpenAI

from . import config, weather, transport

logger = logging.getLogger("agent")

_client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

_GREETING_RE = re.compile(r"^[你侬]好[，,、\s]*", re.UNICODE)

_SYSTEM = (
    "你是一个群聊语音助手。用户通过上海话语音向你提出请求（已由语音识别转成文字）。"
    "根据用户的请求和群里最近的对话内容，给出简洁、有用的回复。"
    "可以总结、翻译、回答问题或执行用户描述的任何操作。只输出回复本身，不要解释。"
    "对话记录中每条消息都带有发言人姓名前缀（格式：姓名：内容）。"
    "当用户说'我'时，指的是下面指定的当前请求者本人，请据此从记录中找到他/她的发言。"
    "如果用户要求总结其他人说了什么，只包含非请求者的发言，排除请求者自己的消息。"
    "需要实时信息（比如天气、气温、会不会下雨、要不要带伞、公交几点来、还要等几分钟）时，"
    "调用提供的工具获取，不要凭空编造。"
)

_CONTEXT_PREFIX = (
    "以下是该群最近的对话内容（按时间先后排列），供你参考：\n\n"
)

# ---- 工具定义 + 分发表 ----
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "查询某地的当前天气和未来几天的天气预报。"
                "当用户问天气、气温、会不会下雨、要不要带伞等问题时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "地点名称，可用中文或英文，例如 'Homebush'、'Sydney'、'悉尼'。"
                            "用户没指定地点时用 'Homebush, Sydney'。"
                        ),
                    },
                    "days": {
                        "type": "integer",
                        "description": "需要预报的天数，1~3，默认 1（只看今天）。",
                    },
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bus_departures",
            "description": (
                "查询某个公交/巴士站点接下来的实时离站班次（NSW Transport 实时数据）。"
                "当用户问公交/巴士/几号车几点来、还要等几分钟、下一班车等问题时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stop": {
                        "type": "string",
                        "description": (
                            "站点名称或数字 stop id，例如 'Underwood Rd before Powell St' "
                            "或 '10118084'。用户没指定站点时留空，用默认站点。"
                        ),
                    },
                    "route": {
                        "type": "string",
                        "description": "线路号过滤，例如 '526'。不指定就返回该站所有线路。",
                    },
                    "count": {
                        "type": "integer",
                        "description": "返回最近几班，默认 2（下两班车）。",
                    },
                },
                "required": [],
            },
        },
    },
]

_DISPATCH = {
    "get_weather": lambda args: weather.get_weather(
        args.get("location") or config.WEATHER_DEFAULT_LOCATION,
        args.get("days", 1),
    ),
    "get_bus_departures": lambda args: transport.get_bus_departures(
        args.get("stop") or config.NSW_TRANSPORT_DEFAULT_STOP,
        args.get("route") or config.NSW_TRANSPORT_DEFAULT_ROUTE,
        args.get("count", 2),
    ),
}

_MAX_TOOL_ROUNDS = 4


def is_agent_trigger(text: str) -> bool:
    return bool(_GREETING_RE.match(text))


def strip_greeting(text: str) -> str:
    return _GREETING_RE.sub("", text).strip()


def _run_tool(name: str, arguments: str) -> str:
    """执行一个工具调用，永不抛异常——失败也返回一段说明喂回模型。"""
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"（未知工具：{name}）"
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    try:
        return str(fn(args))
    except Exception as e:  # noqa: BLE001
        logger.warning("工具 %s 执行失败: %s", name, e)
        return f"（工具 {name} 执行失败：{e}）"


def respond(request: str, context: list[str] | None = None, requester: str = "") -> str:
    system = _SYSTEM
    if requester:
        system += f"\n\n当前请求者：{requester}"
    messages = [{"role": "system", "content": system}]
    if context:
        messages.append({
            "role": "system",
            "content": _CONTEXT_PREFIX + "\n".join(context),
        })
    messages.append({"role": "user", "content": request})

    # 🔁 函数调用循环：模型可多轮调用工具，拿到结果后再生成最终回复。
    for _ in range(_MAX_TOOL_ROUNDS):
        resp = _client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=messages,
            tools=_TOOLS,
            temperature=0.5,
            max_tokens=600,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip()

        # 把带 tool_calls 的 assistant 消息原样回填，再逐个执行工具。
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            logger.info("调用工具 %s(%s)", tc.function.name, tc.function.arguments)
            result = _run_tool(tc.function.name, tc.function.arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # 兜底：轮次用尽仍在调工具，最后不带工具再要一次纯文字回复。
    logger.warning("函数调用循环达到上限 %d 轮，强制收尾", _MAX_TOOL_ROUNDS)
    resp = _client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=600,
    )
    return (resp.choices[0].message.content or "").strip()
