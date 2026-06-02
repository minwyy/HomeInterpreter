"""集中读取环境变量配置。"""
import os
from dotenv import load_dotenv

load_dotenv()


def _req(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"缺少环境变量: {key}")
    return val


# 状态存储路径(SQLite 等)；容器里挂在 /data named volume，本地默认当前目录。
DB_PATH = os.getenv("DB_PATH", "state.db")

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

# 自定义热词(vocabulary)：让 ASR 把指定词识别成原样，比如英文地名 Ashfield。
# FUNASR_VOCABULARY_ID 由 manage_vocab.py 创建后回填到这里(运行时用)。
FUNASR_VOCABULARY_ID = os.getenv("FUNASR_VOCABULARY_ID", "")
# 热词前缀(只能小写字母/数字，<=10 字符)，仅 manage_vocab.py 建表时用。
FUNASR_VOCABULARY_PREFIX = os.getenv("FUNASR_VOCABULARY_PREFIX", "places")
# 要强制识别的词，逗号分隔；默认按英文地名处理(lang=en)。仅 manage_vocab.py 用。
_hot = os.getenv("FUNASR_HOTWORDS", "").strip()
FUNASR_HOTWORDS = [w.strip() for w in _hot.split(",") if w.strip()]

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
