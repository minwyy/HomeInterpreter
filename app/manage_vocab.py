"""管理 Fun-ASR 自定义热词(vocabulary)，用来强制识别英文地名等专有名词。

热词从 .env 的 FUNASR_HOTWORDS 读取(逗号分隔)，默认按英文地名处理(lang=en, weight=4)。

用法：
    python -m app.manage_vocab create        # 用 FUNASR_HOTWORDS 建表，打印 vocabulary_id
    python -m app.manage_vocab list           # 列出本账号已有的热词表
    python -m app.manage_vocab show <id>      # 查看某个表的词条
    python -m app.manage_vocab update <id>    # 用当前 FUNASR_HOTWORDS 覆盖某个表
    python -m app.manage_vocab delete <id>    # 删除某个表

create/update 后，把打印出的 vocabulary_id 填到 .env 的 FUNASR_VOCABULARY_ID。
注意：每个账号最多 10 个表、每表最多 500 词。
"""
import sys

import dashscope
from dashscope.audio.asr import VocabularyService

from . import config


def _setup():
    if not config.DASHSCOPE_API_KEY:
        raise SystemExit("缺少 DASHSCOPE_API_KEY")
    dashscope.api_key = config.DASHSCOPE_API_KEY
    dashscope.base_http_api_url = config.DASHSCOPE_HTTP_URL
    return VocabularyService()


def _vocab() -> list[dict]:
    if not config.FUNASR_HOTWORDS:
        raise SystemExit("FUNASR_HOTWORDS 为空，请在 .env 里填要识别的词(逗号分隔)")
    return [{"text": w, "weight": 4, "lang": "en"} for w in config.FUNASR_HOTWORDS]


def create(svc):
    words = _vocab()
    vid = svc.create_vocabulary(
        target_model=config.FUNASR_MODEL,
        prefix=config.FUNASR_VOCABULARY_PREFIX,
        vocabulary=words,
    )
    print(f"已创建，含 {len(words)} 个词：{[w['text'] for w in words]}")
    print(f"vocabulary_id = {vid}")
    print("把它填到 .env：FUNASR_VOCABULARY_ID=" + vid)


def list_all(svc):
    rows = svc.list_vocabularies(prefix=config.FUNASR_VOCABULARY_PREFIX)
    if not rows:
        print("(没有热词表)")
        return
    for r in rows:
        print(r)


def show(svc, vid):
    for w in svc.query_vocabulary(vid):
        print(w)


def update(svc, vid):
    words = _vocab()
    svc.update_vocabulary(vocabulary_id=vid, vocabulary=words)
    print(f"已更新 {vid}，含 {len(words)} 个词：{[w['text'] for w in words]}")


def delete(svc, vid):
    svc.delete_vocabulary(vid)
    print(f"已删除 {vid}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    svc = _setup()
    if cmd == "create":
        create(svc)
    elif cmd == "list":
        list_all(svc)
    elif cmd in ("show", "update", "delete"):
        if not rest:
            raise SystemExit(f"{cmd} 需要一个 vocabulary_id")
        {"show": show, "update": update, "delete": delete}[cmd](svc, rest[0])
    else:
        raise SystemExit(f"未知命令: {cmd}\n{__doc__}")


if __name__ == "__main__":
    main()
