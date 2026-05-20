import json
import logging
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

from modules.shared.paths import BACKEND_ROOT

logger = logging.getLogger(__name__)

OFFICIAL_SITE_CATALOG_PATH = BACKEND_ROOT / "official_url_allowlist.json"

_RAW_SITE_CATALOG_CACHE: Optional[Dict] = None
_OFFICIAL_SITE_ENTRIES_CACHE: List[Dict] = []
_OFFICIAL_HOST_SETS_CACHE: Optional[Dict[str, Set[str]]] = None


def _dedupe_text_items(values: List[str]) -> List[str]:
    items: List[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _normalize_host(raw_host: str) -> str:
    host = str(raw_host or "").strip().lower()
    if not host:
        return ""
    if host.startswith("http://") or host.startswith("https://"):
        parsed = urlparse(host)
        host = parsed.netloc or parsed.path
    host = host.strip().lstrip(".")
    if "/" in host:
        host = host.split("/", 1)[0]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host


def _load_raw_catalog() -> Dict:
    global _RAW_SITE_CATALOG_CACHE
    if _RAW_SITE_CATALOG_CACHE is not None:
        return _RAW_SITE_CATALOG_CACHE
    if not OFFICIAL_SITE_CATALOG_PATH.exists():
        _RAW_SITE_CATALOG_CACHE = {}
        return _RAW_SITE_CATALOG_CACHE

    try:
        _RAW_SITE_CATALOG_CACHE = json.loads(OFFICIAL_SITE_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("failed to load official site catalog: %s", exc)
        _RAW_SITE_CATALOG_CACHE = {}
    return _RAW_SITE_CATALOG_CACHE


def load_official_site_entries() -> List[Dict]:
    global _OFFICIAL_SITE_ENTRIES_CACHE
    if _OFFICIAL_SITE_ENTRIES_CACHE:
        return _OFFICIAL_SITE_ENTRIES_CACHE

    raw = _load_raw_catalog()
    entries: List[Dict] = []

    def collect(items, restricted: bool) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            host = _normalize_host(str(item.get("host") or item.get("root_url") or ""))
            root_url = str(item.get("root_url") or "").strip()
            if not name or not host or not root_url:
                continue

            aliases = _dedupe_text_items(list(item.get("aliases") or []))
            scenes = _dedupe_text_items(list(item.get("scenes") or []))
            category = str(item.get("category") or "").strip()
            summary = str(item.get("summary") or "").strip()
            access = str(item.get("access") or ("通常需要统一身份认证登录" if restricted else "公开访问")).strip()

            entries.append(
                {
                    "name": name,
                    "host": host,
                    "root_url": root_url,
                    "category": category,
                    "summary": summary,
                    "aliases": aliases,
                    "scenes": scenes,
                    "access": access,
                    "restricted": restricted,
                }
            )

    collect(raw.get("sites"), restricted=False)
    collect(raw.get("restricted_sites"), restricted=True)
    _OFFICIAL_SITE_ENTRIES_CACHE = entries
    return entries


def get_official_site_host_sets() -> Dict[str, Set[str]]:
    global _OFFICIAL_HOST_SETS_CACHE
    if _OFFICIAL_HOST_SETS_CACHE is not None:
        return _OFFICIAL_HOST_SETS_CACHE

    raw = _load_raw_catalog()
    preferred_hosts: Set[str] = set()
    restricted_hosts: Set[str] = set()

    def collect(items, target: Set[str]) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            host = _normalize_host(str(item.get("host") or item.get("root_url") or ""))
            if host:
                target.add(host)

    collect(raw.get("sites"), preferred_hosts)
    collect(raw.get("restricted_sites"), restricted_hosts)
    _OFFICIAL_HOST_SETS_CACHE = {
        "preferred_hosts": preferred_hosts,
        "restricted_hosts": restricted_hosts,
    }
    return _OFFICIAL_HOST_SETS_CACHE