"""可插拔 ASR 层（与微信版同款）。

默认：阿里云百炼 Fun-ASR 非实时（录音文件识别），走新加坡(国际)节点。
- 模型 fun-asr，支持吴语(含上海话)，方言自动处理。
- 只接受公网 URL；Telegram 的语音文件本身就有公网下载 URL，直接传给它。
- Fun-ASR 原生支持 ogg/opus（Telegram 语音格式），无需转码。
"""
from abc import ABC, abstractmethod

from . import config


def _g(obj, key):
    """dashscope 的 output 既可能是 dict 也可能是对象，统一取值。"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


class ASRProvider(ABC):
    @abstractmethod
    def transcribe(self, *, audio_url: str) -> str:
        """audio_url: 公网可下载的音频地址。返回转写文字。"""
        ...


class BailianFunASR(ASRProvider):
    """阿里云百炼 Fun-ASR 非实时（国际/新加坡节点）。"""

    def __init__(self):
        import dashscope

        if not config.DASHSCOPE_API_KEY:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY（新加坡区域的 Key）")
        dashscope.api_key = config.DASHSCOPE_API_KEY
        dashscope.base_http_api_url = config.DASHSCOPE_HTTP_URL
        self._model = config.FUNASR_MODEL

    def transcribe(self, *, audio_url: str) -> str:
        import httpx
        from http import HTTPStatus
        from dashscope.audio.asr import Transcription

        task = Transcription.async_call(
            model=self._model,
            file_urls=[audio_url],
            language_hints=["zh"],  # 偏中文(含吴语/上海话)；想自动检测可去掉
        )
        resp = Transcription.wait(task=task)
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"Fun-ASR 任务失败: {resp.status_code} {getattr(resp, 'message', '')}"
            )

        results = _g(resp.output, "results") or []
        if not results:
            return ""
        sub = results[0]
        if _g(sub, "subtask_status") != "SUCCEEDED":
            raise RuntimeError(
                f"Fun-ASR 子任务失败: {_g(sub, 'code')} {_g(sub, 'message')}"
            )

        turl = _g(sub, "transcription_url")
        data = httpx.get(turl, timeout=30).json()
        texts = [t.get("text", "") for t in data.get("transcripts", [])]
        return "\n".join(t for t in texts if t).strip()


def get_asr() -> ASRProvider:
    provider = config.ASR_PROVIDER.lower()
    if provider == "bailian":
        return BailianFunASR()
    raise RuntimeError(f"未知 ASR_PROVIDER: {provider}")
