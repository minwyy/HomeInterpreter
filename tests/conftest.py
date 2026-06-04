"""测试夹具：在导入 app.* 前塞入假环境变量，并提供临时 SQLite 路径。"""
import os

# 必须在 import app.config 之前设置(config 在导入时校验必填项)。
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("DASHSCOPE_API_KEY", "sk-test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("POLISH_ENABLED", "true")

import pytest

from app import config


@pytest.fixture
def memdb(tmp_path, monkeypatch):
    """把 DB_PATH 指到临时文件；memory.py 在调用时才读 config.DB_PATH，故 monkeypatch 生效。"""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    return config
