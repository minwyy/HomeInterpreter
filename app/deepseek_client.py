"""DeepSeek：把上海话转写整理成规范中文。"""
from openai import OpenAI

from . import config

_client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

_SYSTEM = (
    "你是中文文字整理助手。下面是一段由上海话(吴语)语音识别转写来的中文文字，"
    "可能含方言用词、口语、少量识别错误。请在不改变原意的前提下，整理成通顺、"
    "规范的简体中文书面表达，保留人名、时间、地点、数字等关键信息。"
    "只输出整理后的文字，不要解释、不要加引号。"
)

_CONTEXT_PREFIX = (
    "以下是该群最近的对话内容（已整理，按时间先后排列），仅供参考，帮助你保持人名、"
    "地名、专有名词和用词的一致；不要把这些内容混进本次输出。\n\n"
)


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
