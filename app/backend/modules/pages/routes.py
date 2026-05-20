import os

import requests
from flask import jsonify, request, send_from_directory

from modules.auth.service import PERM_ANSWER, require_permission


TENCENT_MAP_KEY = os.getenv("TENCENT_MAP_KEY", "")
TENCENT_MAP_TIMEOUT = float(os.getenv("TENCENT_MAP_TIMEOUT", "8"))


def _normalize_place_results(items, source: str):
    normalized = []
    seen = set()
    for item in items or []:
        title = str(item.get("title") or item.get("name") or "").strip()
        address = str(item.get("address") or "").strip()
        location = item.get("location") or {}
        try:
            lat = float(location.get("lat"))
            lng = float(location.get("lng"))
        except (TypeError, ValueError):
            continue

        dedupe_key = (title, address, round(lat, 6), round(lng, 6))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(
            {
                "title": title or "未知地点",
                "address": address or "暂无详细地址",
                "location": {"lat": lat, "lng": lng},
                "ad_info": item.get("ad_info") or {},
                "source": source,
            }
        )
    return normalized


def _query_tencent_places(keyword: str):
    if not TENCENT_MAP_KEY:
        return {"items": [], "strategy": "", "error": "map key is not configured"}

    endpoints = (
        (
            "北京地区搜索",
            "https://apis.map.qq.com/ws/place/v1/search",
            {
                "keyword": keyword,
                "boundary": "region(北京,0)",
                "page_size": 10,
                "key": TENCENT_MAP_KEY,
                "output": "json",
            },
        ),
        (
            "北京地区联想",
            "https://apis.map.qq.com/ws/place/v1/suggestion",
            {
                "keyword": keyword,
                "region": "北京",
                "page_size": 10,
                "key": TENCENT_MAP_KEY,
                "output": "json",
            },
        ),
    )

    errors = []
    for strategy, url, params in endpoints:
        try:
            response = requests.get(url, params=params, timeout=TENCENT_MAP_TIMEOUT)
            payload = response.json()
        except Exception as exc:
            errors.append(f"{strategy}: {exc}")
            continue

        status = payload.get("status")
        if status is None or int(status) != 0:
            errors.append(f"{strategy}: {payload.get('message') or payload.get('status')}")
            continue

        items = _normalize_place_results(payload.get("data") or [], source=strategy)
        if items:
            return {"items": items, "strategy": strategy, "error": ""}

    return {"items": [], "strategy": "", "error": "；".join(errors[:2])}


def register_page_routes(app) -> None:
    def page_view(filename: str):
        def _view():
            return send_from_directory(app.static_folder, filename)

        return _view

    public_pages = {
        "/": ("index", "index.html"),
        "/chat": ("chat_page", "chat.html"),
        "/place": ("place_page", "place.html"),
        "/freshman": ("freshman_page", "freshman.html"),
    }
    for path, (endpoint, filename) in public_pages.items():
        app.add_url_rule(path, endpoint=endpoint, view_func=page_view(filename))

    @app.get("/api/place_search")
    def api_place_search():
        keyword = (request.args.get("q") or "").strip()
        if not keyword:
            return jsonify({"error": "q is required"}), 400

        payload = _query_tencent_places(keyword)
        return jsonify(payload)

    @app.get("/senior")
    def senior_page():
        denied = require_permission(PERM_ANSWER)
        if denied:
            return denied
        return send_from_directory(app.static_folder, "senior.html")