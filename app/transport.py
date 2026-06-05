"""NSW Transport Open Data 实时公交departures工具。

作为 agent 函数调用循环(roadmap #7)里的第二个工具：查某个站点接下来的实车
出发时间，可按线路号过滤(默认 526)。用 Trip Planner API 的两个端点：
  - stop_finder：把站名(如"Underwood Rd before Powell St")解析成 stop id
  - departure_mon：拿该站的实时离站事件(stopEvents)
都需要 https://opendata.transport.nsw.gov.au/ 注册的 API key，
经 `Authorization: apikey {KEY}` 传。阻塞 httpx 由调用方在线程里跑。
"""
import logging
from datetime import datetime, timezone

import httpx

from . import config

logger = logging.getLogger("transport")

_BASE = "https://api.transport.nsw.gov.au/v1/tp"

# 站名 → stop id 的进程内缓存，省掉重复的 stop_finder 调用。
_stop_id_cache: dict[str, str] = {}


def _headers() -> dict:
    return {"Authorization": f"apikey {config.NSW_TRANSPORT_API_KEY}"}


def _resolve_stop_id(stop: str) -> str | None:
    """把站名解析成 stop id；已是纯数字 id 就直接返回。失败返回 None。"""
    stop = (stop or "").strip()
    if not stop:
        return None
    if stop.isdigit():
        return stop
    if stop in _stop_id_cache:
        return _stop_id_cache[stop]
    try:
        resp = httpx.get(
            f"{_BASE}/stop_finder",
            params={
                "outputFormat": "rapidJSON",
                "type_sf": "any",
                "name_sf": stop,
                "coordOutputFormat": "EPSG:4326",
                "TfNSWSF": "true",
                "version": "10.2.1.42",
            },
            headers=_headers(),
            timeout=10.0,
        )
        resp.raise_for_status()
        locations = resp.json().get("locations", []) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("stop_finder 失败(%s): %s", stop, e)
        return None

    # 优先 isBest，其次 type==stop，再退到第一个。
    best = next((l for l in locations if l.get("isBest")), None)
    if best is None:
        best = next((l for l in locations if l.get("type") == "stop"), None)
    if best is None and locations:
        best = locations[0]
    stop_id = best.get("id") if best else None
    if stop_id:
        _stop_id_cache[stop] = stop_id
    return stop_id


def _minutes_until(iso: str) -> int | None:
    """ISO8601(UTC) → 距现在的分钟数(向下取整，可为负=已过点)。"""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((dt - datetime.now(timezone.utc)).total_seconds() // 60)


def get_bus_departures(stop: str, route: str = "", limit: int = 4) -> str:
    """查 stop 接下来的离站班次，可按 route 线路号过滤，返回中文摘要字符串。"""
    if not config.NSW_TRANSPORT_API_KEY:
        return "（未配置 NSW_TRANSPORT_API_KEY，无法查询公交实时班次）"
    stop = (stop or config.NSW_TRANSPORT_DEFAULT_STOP).strip()
    route = (route or "").strip()

    stop_id = _resolve_stop_id(stop)
    if not stop_id:
        return f"（找不到站点：{stop}）"

    try:
        resp = httpx.get(
            f"{_BASE}/departure_mon",
            params={
                "outputFormat": "rapidJSON",
                "coordOutputFormat": "EPSG:4326",
                "mode": "direct",
                "type_dm": "stop",
                "name_dm": stop_id,
                "depArrMacro": "dep",
                "TfNSWDM": "true",
                "version": "10.2.1.42",
            },
            headers=_headers(),
            timeout=10.0,
        )
        resp.raise_for_status()
        events = resp.json().get("stopEvents", []) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("departure_mon 失败(%s/%s): %s", stop, stop_id, e)
        return f"（公交班次查询失败：{e}）"

    lines = []
    for ev in events:
        tr = ev.get("transportation", {}) or {}
        number = (tr.get("number") or "").strip()
        if route and number != route:
            continue
        dest = (tr.get("destination", {}) or {}).get("name", "")
        planned = ev.get("departureTimePlanned", "")
        estimated = ev.get("departureTimeEstimated", "")
        when = estimated or planned
        mins = _minutes_until(when)
        realtime = "实时" if estimated else "计划"
        if mins is None:
            eta = when
        elif mins <= 0:
            eta = "即将到站"
        else:
            eta = f"{mins} 分钟后"
        lines.append(f"{number} 路（开往 {dest}）：{eta}（{realtime}）")
        if len(lines) >= limit:
            break

    if not lines:
        which = f"{route} 路" if route else "任何线路"
        return f"{stop}：接下来暂无 {which} 的班次。"
    head = f"{stop}{('，' + route + ' 路') if route else ''} 接下来的班次："
    return head + "\n" + "\n".join(lines)
