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


def polish(transcript: str) -> str:
    if not transcript:
        return ""
    resp = _client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": transcript},
        ],
        temperature=0.3,
        max_tokens=600,
    )
    return resp.choices[0].message.content.strip()
