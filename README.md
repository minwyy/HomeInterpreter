# Telegram 上海话群语音转写 bot

群里有人发上海话语音 → Fun-ASR 转写 → (可选) DeepSeek 整理成规范中文 → bot 回复在群里。

## 为什么 Telegram 能做、微信不能

微信卡在两条死规则上:群里只在被@时才收消息、语音又只在单聊支持。Telegram 没有这两道墙——
**关掉隐私模式或把 bot 设为管理员后,它能收到群里所有消息(含语音)**,而且群成员在成员列表里看得见这个 bot、也看得见它的隐私模式状态,不是隐形监听。

## 流程

```
群里的上海话语音(ogg/opus)
      │  ① getFile 拿到公网下载 URL
      ▼
   Fun-ASR 非实时（吴语/上海话）   ← 原生吃 ogg/opus，无需 ffmpeg
      ▼
   中文转写文字
      │  ② (可选) 整理成规范中文 ← DeepSeek
      ▼
   bot 回复到群里（回复在那条语音下面）
```

长轮询(`run_polling`),**无需公网 IP / webhook / 加解密** —— bot 主动连出去就行。

## 准备

### 1. 建 bot 并关掉隐私模式（关键）
1. 找 [@BotFather](https://t.me/BotFather) 发 `/newbot`,拿到 `TELEGRAM_BOT_TOKEN`。
2. 发 `/setprivacy` → 选你的 bot → 点 **Disable**(关闭隐私模式)。
   - 或者:把 bot 加进群后**设为群管理员**,管理员 bot 无视隐私模式,同样能收全部消息。
3. ⚠️ **改完隐私设置后,必须把 bot 移出群再重新加回去才生效**(Telegram 在 bot 入群时缓存了隐私状态)。

### 2. 阿里云百炼 Fun-ASR（国际/新加坡）
- 在 [Model Studio (Singapore)](https://modelstudio.console.alibabacloud.com/ap-southeast-1) 开通,拿**新加坡区域**的 API Key。

### 3. DeepSeek（可选）
- 只在 `POLISH_ENABLED=true` 时需要。不想要整理、只要原始转写就设 `false`,可省掉这个 Key。

## 运行

```bash
cp .env.example .env        # 填好 token 和密钥
pip install -r requirements.txt
python -m app.bot
```

把 bot 拉进群、关掉隐私模式(并重新加回)后,群里发上海话语音,bot 会回一条中文。

## 文件结构

```
app/
├── bot.py             Telegram 入口：长轮询 + 语音 handler（阻塞调用走线程，不卡事件循环）
├── config.py          从环境变量读配置
├── asr.py             可插拔 ASR，默认 Fun-ASR 非实时（吴语/上海话），按 URL 识别
└── deepseek_client.py 把转写整理成规范中文
```

## 注意

- **Token 暴露**:Telegram 文件 URL 里带着 bot token,直接交给 Fun-ASR 去抓,等于把 token 暴露给阿里那边(经 https)。家庭量级影响很小。介意的话:把语音下载成字节、改用**实时 Fun-ASR**(收本地字节、不需要 URL),token 就不出本机。
- **群里会很吵**:每条语音都回一条。想只处理特定群,用 `ALLOWED_CHAT_IDS` 白名单。想加触发条件(比如只在被回复/@时才转),在 `on_voice` 里加判断即可。
- **延迟**:非实时 Fun-ASR 任务先排队(通常几秒,偶尔几分钟),所以先回「识别中…」占位,出结果再编辑那条消息。
- **透明性**:Telegram 技术上允许你这么做,但群成员看得见 bot 在场。监听并转写他人语音,最好在群里说明一下。
- **上海话精度**:国际区是 `fun-asr`,吴语自动识别。不理想的话可换北京区 Key + 改 `DASHSCOPE_HTTP_URL`,代码不动。

## 后续可做
- 去重(同一 file_id 不重复识别)、把转写写进数据库做整群纪要。
- 多条语音合并成一段会话上下文,喂 DeepSeek 出"群聊摘要"而非逐条转写。
- 打包 Dockerfile + systemd,跟你 pims-micro 的部署方式对齐。
