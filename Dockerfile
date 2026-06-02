# 上海话群语音转写 bot —— 长轮询，无入站端口，纯出站连接。
FROM python:3.14.5-slim-trixie

# 不写 .pyc、日志不缓冲(docker logs 实时可见)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码(.env 不进镜像，见 .dockerignore)
COPY app ./app

# 状态(SQLite 等)写到挂载的 named volume，见 docker-compose.yml
ENV DB_PATH=/data/state.db
VOLUME ["/data"]

CMD ["python", "-m", "app.bot"]
