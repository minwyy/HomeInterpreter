"""Telegram 群语音转写 bot。

群里有人发上海话语音 → Fun-ASR 转写 → (可选) DeepSeek 整理成规范中文 → bot 回复。

长轮询(run_polling)，无需公网 IP / webhook。
重要：去 BotFather 把隐私模式关掉(/setprivacy → Disable)，或把 bot 设为群管理员，
否则 bot 在群里收不到普通语音消息。改完后需把 bot 移出群再加回去才生效。
"""
import asyncio
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from . import config, asr, deepseek_client

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

        # ASR 和 DeepSeek 都是阻塞调用，丢到线程里，别卡住事件循环
        transcript = await asyncio.to_thread(_asr_client().transcribe, audio_url=url)
        if not transcript:
            await placeholder.edit_text("（没识别到语音内容）")
            return

        if config.POLISH_ENABLED:
            text = await asyncio.to_thread(deepseek_client.polish, transcript)
        else:
            text = transcript

        await placeholder.edit_text(f"🎙 {text}")
    except Exception as e:  # noqa: BLE001
        logger.exception("处理语音失败")
        try:
            await placeholder.edit_text(f"语音识别失败：{e}")
        except Exception:
            logger.exception("连失败提示都没发出去")


def main() -> None:
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    logger.info("bot 启动，长轮询中…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
