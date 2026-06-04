"""Telegram 群语音转写 bot。

群里有人发上海话语音 → Fun-ASR 转写 → (可选) DeepSeek 整理成规范中文 → bot 回复。

长轮询(run_polling)，无需公网 IP / webhook。
重要：去 BotFather 把隐私模式关掉(/setprivacy → Disable)，或把 bot 设为群管理员，
否则 bot 在群里收不到普通语音消息。改完后需把 bot 移出群再加回去才生效。
"""
import asyncio
import logging
import random

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from . import config, asr, deepseek_client, memory, agent

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logger = logging.getLogger("bot")

_asr = None


def _asr_client():
    global _asr
    if _asr is None:
        _asr = asr.get_asr()
    return _asr


def _allowed(chat_id: int) -> bool:
    return not config.ALLOWED_CHAT_IDS or chat_id in config.ALLOWED_CHAT_IDS


def _speaker(msg) -> str:
    """取发送者显示名：优先 full_name，退而 username，再退空串。"""
    u = getattr(msg, "from_user", None)
    if not u:
        return ""
    return u.full_name or u.username or ""


async def _retry(fn, *, attempts, base_delay, what, on_retry=None, **kwargs):
    """在线程里跑阻塞函数 fn(**kwargs)，只对【异常】(超时/5xx/限流等瞬时错误)重试。

    指数退避 + 抖动，退避用 asyncio.sleep，不阻塞事件循环。空结果不算失败，
    不重试(ASR 对同一音频是确定性的，重试只会得到同样的空)。
    """
    for i in range(attempts):
        try:
            return await asyncio.to_thread(fn, **kwargs)
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            delay = base_delay * (2 ** i) + random.uniform(0, base_delay)
            logger.warning("%s 第%d/%d次失败: %s，%.1fs后重试", what, i + 1, attempts, e, delay)
            if on_retry:
                try:
                    await on_retry(i + 1)
                except Exception:  # noqa: BLE001
                    pass  # 进度提示失败不影响重试
            await asyncio.sleep(delay)


async def _polish(transcript: str, context: list[str] | None = None) -> str:
    """整理转写文字：空结果或出错时重试一次；最终仍失败/为空则回退到原始转写。"""
    for attempt in range(2):  # 初次 + 1 次重试
        try:
            text = await asyncio.to_thread(deepseek_client.polish, transcript, context)
        except Exception as e:  # noqa: BLE001
            logger.warning("DeepSeek 第%d次失败: %s", attempt + 1, e)
            text = ""
        if text:
            return text
        if attempt == 0:
            logger.info("DeepSeek 返回空/出错，重试一次…")
            await asyncio.sleep(1.0)
    logger.info("DeepSeek 整理未成功，回退到原始转写")
    return transcript


def _file_url(file_path: str) -> str:
    """把 getFile 返回的 file_path 拼成可公网下载的完整 URL。"""
    if file_path.startswith("http"):
        return file_path
    return f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{file_path}"


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "上海话语音转写已就绪。把我加进群、关掉隐私模式后，群里发语音我就转成中文。"
    )


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    if not _allowed(chat.id):
        return

    voice = msg.voice or msg.audio  # 兼容语音消息和音频文件
    if not voice:
        return

    placeholder = await msg.reply_text("🎧 识别中…", reply_to_message_id=msg.message_id)
    try:
        f = await context.bot.get_file(voice.file_id)
        url = _file_url(f.file_path)

        # ASR 和 DeepSeek 都是阻塞调用，丢到线程里，别卡住事件循环。
        # ASR 只对瞬时异常重试(最多3次)；返回空表示确定性"没识别到"，不重试。
        logger.info("ASR 开始: %s", url)
        transcript = await _retry(
            _asr_client().transcribe,
            attempts=3,
            base_delay=1.0,
            what="ASR",
            on_retry=lambda n: placeholder.edit_text(f"🎧 识别重试中…({n + 1}/3)"),
            audio_url=url,
        )
        logger.info("ASR 结果: %s", transcript)
        if not transcript:
            await placeholder.edit_text("（没识别到语音内容）")
            return

        # Agent mode: voice starts with 你好 / 侬好 → let DeepSeek handle freely.
        if agent.is_agent_trigger(transcript):
            request = agent.strip_greeting(transcript)
            logger.info("Agent 请求: %r", request)
            memory_context = (
                await asyncio.to_thread(memory.recent, chat.id)
                if config.MEMORY_ENABLED
                else []
            )
            reply = await asyncio.to_thread(agent.respond, request, memory_context, _speaker(msg))
            await placeholder.edit_text(f"🤖 {reply}")
            return

        # Normal flow: polish and store in memory.
        if config.POLISH_ENABLED:
            memory_context = (
                await asyncio.to_thread(memory.recent, chat.id)
                if config.MEMORY_ENABLED
                else []
            )
            logger.info("DeepSeek 整理中…（上下文 %d 条）", len(memory_context))
            text = await _polish(transcript, memory_context)
            logger.info("DeepSeek 结果: %s", text)
        else:
            text = transcript

        await placeholder.edit_text(f"🎙 {text}")

        if config.POLISH_ENABLED and config.MEMORY_ENABLED:
            await asyncio.to_thread(
                memory.add, chat.id, text, ts=msg.date.timestamp(), speaker=_speaker(msg)
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("处理语音失败")
        try:
            await placeholder.edit_text(f"语音识别失败：{e}")
        except Exception:
            logger.exception("连失败提示都没发出去")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """把群里的文字消息也记进一天记忆，供后续整理时当上下文；不回复。"""
    if not (config.POLISH_ENABLED and config.MEMORY_ENABLED):
        return
    msg = update.effective_message
    chat = update.effective_chat
    if not _allowed(chat.id) or not msg or not msg.text:
        return
    await asyncio.to_thread(
        memory.add, chat.id, msg.text, ts=msg.date.timestamp(), speaker=_speaker(msg)
    )


def main() -> None:
    memory.init()
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    logger.info("bot 启动，长轮询中…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
