"""Agent mode: voice starting with '你好'/'侬好' is sent to DeepSeek as a
free-form request rather than a transcription to polish.  DeepSeek decides
what to do (summarise, translate, answer a question, etc.) based on the
request and the recent group conversation context.
"""
import re
from openai import OpenAI

from . import config

_client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

_GREETING_RE = re.compile(r"^[你侬]好[，,、\s]*", re.UNICODE)

_SYSTEM = (
    "你是一个群聊语音助手。用户通过上海话语音向你提出请求（已由语音识别转成文字）。"
    "根据用户的请求和群里最近的对话内容，给出简洁、有用的回复。"
    "可以总结、翻译、回答问题或执行用户描述的任何操作。只输出回复本身，不要解释。"
    "对话记录中每条消息都带有发言人姓名前缀（格式：姓名：内容）。"
    "当用户说"我"时，指的是下面指定的当前请求者本人，请据此从记录中找到他/她的发言。"
)

_CONTEXT_PREFIX = (
    "以下是该群最近的对话内容（按时间先后排列），供你参考：\n\n"
)


def is_agent_trigger(text: str) -> bool:
    return bool(_GREETING_RE.match(text))


def strip_greeting(text: str) -> str:
    return _GREETING_RE.sub("", text).strip()


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
    resp = _client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=600,
    )
    return resp.choices[0].message.content.strip()
