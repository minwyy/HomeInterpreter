"""WeatherAPI.com 客户端：当前天气 + 短期预报。

作为 agent 函数调用循环(roadmap #6)里的工具被调用，返回一段紧凑的中文摘要，
由 DeepSeek 再加工成最终回复。阻塞的 httpx 调用由调用方在线程里跑，不卡事件循环。
"""
import logging
import httpx

from . import config

logger = logging.getLogger("weather")

_BASE = "https://api.weatherapi.com/v1"


def get_weather(location: str, days: int = 1) -> str:
    """查 location 的当前天气和未来 days 天预报(1~3)，返回中文摘要字符串。"""
    if not config.WEATHERAPI_KEY:
        return "（未配置 WEATHERAPI_KEY，无法查询天气）"
    location = (location or config.WEATHER_DEFAULT_LOCATION).strip()
    try:
        days = max(1, min(int(days or 1), 3))
    except (TypeError, ValueError):
        days = 1
    try:
        resp = httpx.get(
            f"{_BASE}/forecast.json",
            params={"key": config.WEATHERAPI_KEY, "q": location, "days": days, "aqi": "no"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("天气查询失败(%s): %s", location, e)
        return f"（天气查询失败：{e}）"

    loc = data.get("location", {})
    cur = data.get("current", {})
    name = loc.get("name", location)
    region = loc.get("region", "")
    head = f"{name}{('，' + region) if region else ''}"
    lines = [
        f"地点：{head}",
        (
            f"当前：{cur.get('temp_c')}°C，{cur.get('condition', {}).get('text', '')}，"
            f"体感 {cur.get('feelslike_c')}°C，湿度 {cur.get('humidity')}%，"
            f"风 {cur.get('wind_kph')} km/h"
        ),
    ]
    for day in data.get("forecast", {}).get("forecastday", []):
        d = day.get("day", {})
        lines.append(
            f"{day.get('date')}：{d.get('mintemp_c')}~{d.get('maxtemp_c')}°C，"
            f"{d.get('condition', {}).get('text', '')}，"
            f"降雨概率 {d.get('daily_chance_of_rain')}%"
        )
    return "\n".join(lines)
