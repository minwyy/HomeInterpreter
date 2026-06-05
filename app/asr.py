"""可插拔 ASR 层（与微信版同款）。

默认：阿里云百炼 Fun-ASR 非实时（录音文件识别），走新加坡(国际)节点。
- 模型 fun-asr，支持吴语(含上海话)，方言自动处理。
- 只接受公网 URL；Telegram 的语音文件本身就有公网下载 URL，直接传给它。
- Fun-ASR 原生支持 ogg/opus（Telegram 语音格式），无需转码。

备选(ASR_PROVIDER=qwen)：Qwen3-ASR（qwen3-asr-flash），走 MultiModalConversation。
- 单次最长约 3 分钟/10MB，超过就用 ffmpeg 切片后逐片识别再拼接（需装 ffmpeg）。
- 热词偏置走 system 消息文本(复用 FUNASR_HOTWORDS)，没有 vocabulary_id。
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

        kwargs = {}
        if config.FUNASR_VOCABULARY_ID:
            kwargs["vocabulary_id"] = config.FUNASR_VOCABULARY_ID  # 自定义热词，固定英文地名等
        task = Transcription.async_call(
            model=self._model,
            file_urls=[audio_url],
            language_hints=["zh", "en"],  # 中文(含吴语/上海话)+英文，识别夹带的英文地名等
            **kwargs,
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


def _build_context(hotwords: list[str]) -> str:
    """把热词地名拼成给 Qwen 的上下文偏置文本。

    Qwen3-ASR 没有 Fun-ASR 那种 vocabulary_id；偏置走 system 消息里的自由文本
    （官方上限约 1 万 token）。把英文地名/人名列进去，提示模型按原样识别。
    """
    if not hotwords:
        return ""
    return "可能出现的专有名词（地名/人名），请按原样识别：" + "、".join(hotwords)


def _extract_text(resp) -> str:
    """从 MultiModalConversation 响应里取转写文字。

    content 可能是 [{"text": ...}, ...] 也可能直接是字符串；output/message 可能是
    dict 或对象，统一用 _g 兼容。
    """
    output = _g(resp, "output")
    choices = _g(output, "choices") or []
    if not choices:
        return ""
    message = _g(choices[0], "message")
    content = _g(message, "content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(_g(part, "text") or "" for part in content).strip()
    return ""


def _segment_plan(duration: float, max_seconds: float) -> list[tuple[float, float]]:
    """把 [0, duration) 切成每片 <= max_seconds 的 (start, length) 列表，无缝无重叠。"""
    if duration <= max_seconds:
        return [(0.0, duration)]
    plan: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        length = min(max_seconds, duration - start)
        plan.append((start, length))
        start += length
    return plan


def _probe_duration(audio: str) -> float | None:
    """用 ffprobe 读音频时长（秒）。URL 也能直接读；读不到返回 None（退化为单次调用）。"""
    import subprocess

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _split_audio(audio_url: str, max_seconds: float, tmpdir: str) -> list[str]:
    """下载远程音频并用 ffmpeg 切成 <=max_seconds 的 mp3 片段，返回片段文件路径。"""
    import os
    import subprocess

    import httpx

    src = os.path.join(tmpdir, "src")
    with httpx.stream("GET", audio_url, timeout=60) as r:
        r.raise_for_status()
        with open(src, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)

    duration = _probe_duration(src) or 0.0
    paths: list[str] = []
    for i, (start, length) in enumerate(_segment_plan(duration, max_seconds)):
        out = os.path.join(tmpdir, f"chunk{i:03d}.mp3")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(length),
             "-i", src, out],
            check=True, timeout=180,
        )
        paths.append(out)
    return paths


class QwenASR(ASRProvider):
    """阿里云百炼 Qwen3-ASR（qwen3-asr-flash），走 MultiModalConversation 接口。

    与 Fun-ASR 的差异：单次最长约 3 分钟/10MB，超过就用 ffmpeg 切片后逐片识别再拼接；
    热词偏置走 system 消息文本，不用 vocabulary_id。
    """

    def __init__(self):
        import dashscope

        if not config.DASHSCOPE_API_KEY:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY（新加坡区域的 Key）")
        dashscope.api_key = config.DASHSCOPE_API_KEY
        dashscope.base_http_api_url = config.DASHSCOPE_HTTP_URL
        self._model = config.QWEN_ASR_MODEL
        self._context = _build_context(config.FUNASR_HOTWORDS)
        self._max_seconds = config.QWEN_ASR_MAX_CHUNK_SECONDS

    def transcribe(self, *, audio_url: str) -> str:
        duration = _probe_duration(audio_url)
        if duration is None or duration <= self._max_seconds:
            return self._transcribe_one(audio_url)  # 不切片，URL 直接喂给 Qwen

        import shutil
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix="qwenasr_")
        try:
            texts = [self._transcribe_one(c) for c in _split_audio(audio_url, self._max_seconds, tmpdir)]
            return " ".join(t for t in texts if t).strip()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _transcribe_one(self, audio: str) -> str:
        """识别单个音频（URL 或本地切片文件）。"""
        import os
        from http import HTTPStatus

        from dashscope import MultiModalConversation

        ref = audio
        if not (audio.startswith("http://") or audio.startswith("https://") or audio.startswith("file://")):
            ref = "file://" + os.path.abspath(audio)  # 本地切片文件

        messages = []
        if self._context:
            messages.append({"role": "system", "content": [{"text": self._context}]})
        messages.append({"role": "user", "content": [{"audio": ref}]})

        asr_options = {"enable_itn": True}  # 口语数字→书面数字
        if config.QWEN_ASR_LANGUAGE:
            asr_options["language"] = config.QWEN_ASR_LANGUAGE  # 留空则模型自动检测语种

        resp = MultiModalConversation.call(
            model=self._model, messages=messages, asr_options=asr_options
        )
        if _g(resp, "status_code") != HTTPStatus.OK:
            raise RuntimeError(
                f"Qwen-ASR 失败: {_g(resp, 'status_code')} {_g(resp, 'message') or ''}"
            )
        return _extract_text(resp)


def get_asr() -> ASRProvider:
    provider = config.ASR_PROVIDER.lower()
    if provider == "bailian":
        return BailianFunASR()
    if provider == "qwen":
        return QwenASR()
    raise RuntimeError(f"未知 ASR_PROVIDER: {provider}")
