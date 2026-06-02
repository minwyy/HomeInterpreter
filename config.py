"""集中读取环境变量配置。"""
import os
from dotenv import load_dotenv

load_dotenv()


def _req(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"缺少环境变量: {key}")
    return val


# Telegram
TELEGRAM_BOT_TOKEN = _req("TELEGRAM_BOT_TOKEN")

# 只在这些群里生效(逗号分隔的 chat_id);留空 = 所有群都生效
_ids = os.getenv("ALLOWED_CHAT_IDS", "").strip()
ALLOWED_CHAT_IDS = {int(x) for x in _ids.split(",") if x.strip()} if _ids else set()

# ASR 后端
ASR_PROVIDER = os.getenv("ASR_PROVIDER", "bailian")

# 阿里云百炼 Fun-ASR 非实时（默认）
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
# 国际(新加坡)节点；北京节点用 https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_HTTP_URL = os.getenv(
    "DASHSCOPE_HTTP_URL", "https://dashscope-intl.aliyuncs.com/api/v1"
)
FUNASR_MODEL = os.getenv("FUNASR_MODEL", "fun-asr")

# DeepSeek（把上海话转写整理成规范中文；可关）
POLISH_ENABLED = os.getenv("POLISH_ENABLED", "true").lower() == "true"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

if ASR_PROVIDER == "bailian" and not DASHSCOPE_API_KEY:
    raise RuntimeError("缺少 DASHSCOPE_API_KEY（新加坡区域的 Key）")
if POLISH_ENABLED and not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "POLISH_ENABLED=true 需要 DEEPSEEK_API_KEY；只想要原始转写就设 POLISH_ENABLED=false"
    )
