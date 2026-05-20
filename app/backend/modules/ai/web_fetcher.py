import json
import os
import re
import time
import ipaddress
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from modules.ai.official_sites import get_official_site_host_sets
from modules.shared.text_utils import char_ngrams, normalize_text

FETCH_TIMEOUT = float(os.getenv("WEB_FETCH_TIMEOUT", "8"))
MAX_FETCH_URLS = max(1, int(os.getenv("WEB_FETCH_MAX_URLS", "3")))
MAX_FETCH_CHARS = max(800, int(os.getenv("WEB_FETCH_MAX_CHARS", "12000")))
MIN_WEB_CONTENT_LENGTH = max(32, int(os.getenv("WEB_FETCH_MIN_CONTENT_LENGTH", "80")))
ROBOTS_CACHE_TTL = max(60, int(os.getenv("WEB_FETCH_ROBOTS_CACHE_TTL", "1800")))
USER_AGENT = os.getenv(
    "WEB_FETCH_USER_AGENT",
    "BIT Freshman Assistant/1.0 (+controlled web fetch)",
)
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
WEB_SEARCH_TIMEOUT = float(os.getenv("WEB_SEARCH_TIMEOUT", str(FETCH_TIMEOUT)))
WEB_SEARCH_MAX_RESULTS = max(1, int(os.getenv("WEB_SEARCH_MAX_RESULTS", "6")))
WEB_SEARCH_FETCH_LIMIT = max(1, int(os.getenv("WEB_SEARCH_FETCH_LIMIT", str(MAX_FETCH_URLS))))
WEB_FETCH_CONCURRENCY = max(1, int(os.getenv("WEB_FETCH_CONCURRENCY", str(WEB_SEARCH_MAX_RESULTS))))
ROBOTS_FETCH_TIMEOUT = max(0.5, float(os.getenv("WEB_FETCH_ROBOTS_TIMEOUT", "2")))
SEARCH_USER_AGENT = os.getenv("WEB_SEARCH_USER_AGENT", USER_AGENT)
if SEARCH_USER_AGENT == USER_AGENT:
    SEARCH_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
SEARCH_HEADERS = {
    "User-Agent": SEARCH_USER_AGENT,
    "Accept-Language": os.getenv("WEB_SEARCH_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9,en;q=0.8"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}
WEB_SEARCH_DUCKDUCKGO_URL = os.getenv("WEB_SEARCH_DUCKDUCKGO_URL", "https://duckduckgo.com/html/?q={query}")
WEB_SEARCH_SO360_URL = os.getenv("WEB_SEARCH_SO360_URL", "https://www.so.com/s?q={query}")
WEB_SEARCH_BAIDU_URL = os.getenv("WEB_SEARCH_BAIDU_URL", "https://www.baidu.com/s?wd={query}")

VALID_CANDIDATE_URL_PATTERN = re.compile(r'^https?://[^\s"\'>]+')
_ROBOTS_CACHE: Dict[str, Tuple[float, RobotFileParser]] = {}
_SEARCH_REDIRECT_CACHE: Dict[str, str] = {}
_BLOCKED_HOSTS = {"localhost", "0.0.0.0", "127.0.0.1", "::1"}
_LOW_TRUST_HOST_SUFFIXES = (
    ".zhihu.com",
    ".csdn.net",
    ".sohu.com",
    ".baidu.com",
    ".toutiao.com",
)
_SEARCH_PROVIDER_HOST_SUFFIXES = (
    "baidu.com",
    "bdstatic.com",
    "bcebos.com",
    "so.com",
    "360.cn",
    "360kan.com",
    "360tres.com",
    "sm.cn",
)
_SEARCH_PROVIDER_CONTENT_HOSTS = {
    "baike.baidu.com",
    "baijiahao.baidu.com",
    "haokan.baidu.com",
    "jingyan.baidu.com",
    "mbd.baidu.com",
    "quanmin.baidu.com",
    "tieba.baidu.com",
    "baike.so.com",
    "m.map.360.cn",
    "map.360.cn",
    "wenku.so.com",
}
_QUERY_STOPWORDS = (
    "北京理工大学",
    "北理工",
    "有哪些",
    "什么",
    "是谁",
    "谁",
    "怎么",
    "哪个",
    "哪家",
    "哪几个",
    "几家",
    "推荐",
    "呀",
    "啊",
    "的",
    "是",
    "介绍",
    "一下",
    "好吃的",
    "好吃",
    "吗",
    "呢",
)
_BIT_QUERY_TERMS = (
    "北京理工大学",
    "北理工",
    "bit.edu.cn",
    "迎新",
    "新生",
    "报到",
    "宿舍",
    "校区",
    "校园",
    "校园卡",
    "校园网",
    "教务",
    "选课",
    "奖学金",
    "军训",
    "学号",
    "研究生院",
    "本科生院",
    "良乡",
    "中关村",
)
_BIT_CONTEXT_TERMS = (
    "食堂",
    "图书馆",
    "校医院",
    "辅导员",
    "宿管",
    "快递",
    "统一身份",
    "统一身份认证",
    "智慧北理",
    "webvpn",
    "vpn",
    "一卡通",
    "校历",
    "缓考",
    "转专业",
    "绩点",
    "保研",
    "社团",
    "后勤",
    "绿色通道",
    "助学金",
    "助学贷款",
    "勤工助学",
    "资助",
)
_OTHER_UNIVERSITY_MARKERS = (
    "北京大学",
    "北大",
    "清华大学",
    "清华",
    "中国人民大学",
    "人大",
    "北京航空航天大学",
    "北航",
    "北京师范大学",
    "北师大",
    "中国传媒大学",
    "中传",
    "复旦大学",
    "上海交通大学",
    "浙大",
    "浙江大学",
    "南京大学",
    "武汉大学",
    "哈尔滨工业大学",
    "哈工大",
    "同济大学",
)

_SUBJECTIVE_WEB_QUERY_TERMS = (
    "好吃",
    "推荐",
    "体验",
    "怎么样",
    "口碑",
    "值得",
    "攻略",
    "美食",
)

ROBOTS_CACHE_MAX_SIZE = max(16, int(os.getenv("WEB_FETCH_ROBOTS_CACHE_MAX_SIZE", "128")))
SEARCH_REDIRECT_TIMEOUT = max(1.0, float(os.getenv("WEB_SEARCH_REDIRECT_TIMEOUT", "4")))


def _is_restricted_host(host: str) -> bool:
    normalized = _normalize_host(host)
    restricted_hosts = get_official_site_host_sets().get("restricted_hosts") or set()
    return normalized in restricted_hosts


def _is_preferred_official_host(host: str) -> bool:
    normalized = _normalize_host(host)
    if not normalized or _is_restricted_host(normalized):
        return False
    preferred_hosts = get_official_site_host_sets().get("preferred_hosts") or set()
    return normalized in preferred_hosts or normalized.endswith(".bit.edu.cn") or normalized == "bit.edu.cn"


def _is_authoritative_public_host(host: str) -> bool:
    normalized = _normalize_host(host)
    if not normalized:
        return False
    return (
        _is_preferred_official_host(normalized)
        or normalized.endswith(".edu.cn")
        or normalized.endswith(".edu")
        or normalized.endswith(".gov.cn")
    )


def _should_keep_third_party_web_results(question: str) -> bool:
    normalized_question = normalize_text(question, compact=True)
    if not normalized_question:
        return False
    return any(token in normalized_question for token in _SUBJECTIVE_WEB_QUERY_TERMS)


def _prune_robots_cache(now: float) -> None:
    expired_keys = [base for base, (ts, _) in _ROBOTS_CACHE.items() if now - ts >= ROBOTS_CACHE_TTL]
    for base in expired_keys:
        _ROBOTS_CACHE.pop(base, None)

    overflow = len(_ROBOTS_CACHE) - ROBOTS_CACHE_MAX_SIZE
    if overflow >= 0:
        oldest = sorted(_ROBOTS_CACHE.items(), key=lambda item: item[1][0])[: overflow + 1]
        for base, _ in oldest:
            _ROBOTS_CACHE.pop(base, None)


def _normalize_host(netloc: str) -> str:
    host = (netloc or "").strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if ":" in host and host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host


def is_safe_public_url(url: str) -> Tuple[bool, str]:
    normalized = normalize_url(url)
    if not normalized:
        return (False, "网址格式无效")

    host = _normalize_host(urlparse(normalized).netloc)
    if not host:
        return (False, "网址缺少主机名")
    if host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        return (False, "为避免访问本机或内网地址，已拒绝该网址")

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return (False, "为避免访问本机或内网地址，已拒绝该网址")
    except ValueError:
        pass

    return (True, "ok")

def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    cleaned = parsed._replace(fragment="")
    return urlunparse(cleaned)

def _get_robot_parser(url: str) -> RobotFileParser:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    now = time.time()
    _prune_robots_cache(now)
    cached = _ROBOTS_CACHE.get(base)
    if cached and now - cached[0] < ROBOTS_CACHE_TTL:
        return cached[1]

    parser = RobotFileParser()
    robots_url = f"{base}/robots.txt"
    parser.set_url(robots_url)
    try:
        response = requests.get(
            robots_url,
            headers={"User-Agent": USER_AGENT},
            timeout=ROBOTS_FETCH_TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            parser.allow_all = True
        else:
            parser.parse(_decode_response_text(response).splitlines())
    except requests.RequestException:
        parser.allow_all = True
    _ROBOTS_CACHE[base] = (now, parser)
    return parser


def can_fetch(url: str) -> bool:
    parser = _get_robot_parser(url)
    try:
        return bool(parser.can_fetch(USER_AGENT, url))
    except Exception:
        return True


def _extract_text_from_html(html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "form", "svg"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    preferred_nodes = soup.select("main, article, .content, .article, .news, .post, .detail, .container")
    nodes = preferred_nodes or [soup.body or soup]

    chunks: List[str] = []
    seen = set()
    for node in nodes:
        for element in node.find_all(["h1", "h2", "h3", "p", "li"], limit=400):
            text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
            if len(text) < 8 or text in seen:
                continue
            seen.add(text)
            chunks.append(text)
        if len("\n".join(chunks)) >= MAX_FETCH_CHARS:
            break

    if not chunks:
        fallback = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        chunks = [fallback[:MAX_FETCH_CHARS]] if fallback else []

    text = "\n".join(chunks)
    return (title, text[:MAX_FETCH_CHARS].strip())


def _decode_response_text(response: requests.Response) -> str:
    encoding = (response.encoding or "").lower()
    if not encoding or encoding == "iso-8859-1":
        apparent = getattr(response, "apparent_encoding", "") or "utf-8"
        response.encoding = apparent
    return response.text


def _fetch_html_page(normalized: str, site: Optional[Dict], steps: List[Dict]) -> Dict:
    robots_allowed = can_fetch(normalized)
    steps.append(
        {
            "stage": "robots",
            "ok": robots_allowed,
            "message": "robots.txt 允许抓取" if robots_allowed else "robots.txt 不允许抓取",
            "url": normalized,
        }
    )
    if not robots_allowed:
        return {
            "ok": False,
            "url": normalized,
            "site": site,
            "steps": steps,
            "error": "robots.txt 不允许抓取该网址",
        }

    try:
        response = requests.get(
            normalized,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        steps.append({"stage": "request", "ok": False, "message": str(exc), "url": normalized})
        return {
            "ok": False,
            "url": normalized,
            "site": site,
            "steps": steps,
            "error": f"请求失败: {exc}",
        }

    content_type = str(response.headers.get("Content-Type") or "")
    steps.append(
        {
            "stage": "request",
            "ok": True,
            "message": f"HTTP {response.status_code}，Content-Type={content_type or 'unknown'}",
            "url": response.url,
        }
    )

    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        return {
            "ok": False,
            "url": normalized,
            "site": site,
            "steps": steps,
            "error": f"暂不支持抓取该内容类型: {content_type or 'unknown'}",
        }

    title, text = _extract_text_from_html(_decode_response_text(response))
    if not text:
        steps.append({"stage": "extract", "ok": False, "message": "未提取到有效正文", "url": response.url})
        return {
            "ok": False,
            "url": normalized,
            "site": site,
            "steps": steps,
            "error": "未提取到有效正文",
        }

    if len(text) < MIN_WEB_CONTENT_LENGTH:
        steps.append({"stage": "extract", "ok": False, "message": f"正文过短，仅 {len(text)} 字符", "url": response.url})
        return {
            "ok": False,
            "url": normalized,
            "site": site,
            "steps": steps,
            "error": f"正文过短，仅 {len(text)} 字符",
        }

    steps.append(
        {
            "stage": "extract",
            "ok": True,
            "message": f"提取正文成功，长度 {len(text)} 字符",
            "url": response.url,
        }
    )

    return {
        "ok": True,
        "url": normalized,
        "final_url": response.url,
        "site": site,
        "title": title or str((site or {}).get("name") or response.url),
        "text": text,
        "excerpt": text[:360].strip(),
        "steps": steps,
    }

def fetch_public_web_url(url: str, title: str = "", snippet: str = "") -> Dict:
    steps: List[Dict] = []
    normalized = normalize_url(url)
    safe, message = is_safe_public_url(normalized)
    steps.append({"stage": "public_web", "ok": safe, "message": message if not safe else "公网网页校验通过", "url": normalized})
    if not safe:
        return {
            "ok": False,
            "url": normalized,
            "site": None,
            "steps": steps,
            "error": message,
        }

    host = _normalize_host(urlparse(normalized).netloc)
    site = {"name": title or host, "host": host, "category": "全网搜索", "crawl_enabled": True}
    result = _fetch_html_page(normalized, site, steps)
    if result.get("ok"):
        if title and not result.get("title"):
            result["title"] = title
        if snippet:
            result["search_snippet"] = snippet
    return result

def build_web_reference(results: List[Dict]) -> str:
    parts = []
    for item in results:
        if not item.get("ok") and not item.get("search_only"):
            continue
        title = str(item.get("title") or item.get("final_url") or item.get("url") or "网页")
        final_url = str(item.get("final_url") or item.get("url") or "")
        excerpt = str(item.get("excerpt") or item.get("search_snippet") or item.get("text") or "").strip()
        if len(excerpt) > 480:
            excerpt = excerpt[:480].rstrip() + "..."
        source_label = "搜索摘要" if item.get("search_only") and not item.get("ok") else "网页来源"
        parts.append(f"({source_label}:{title} url:{final_url}) {excerpt}")
    return "\n\n".join(parts)


def format_web_sources_markdown(results: List[Dict]) -> str:
    lines = ["### 本次访问网址"]
    seen = set()
    for item in results:
        if not item.get("ok") and not item.get("search_only"):
            continue
        url = str(item.get("final_url") or item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        title = str(item.get("title") or item.get("site", {}).get("name") or url)
        suffix = "（搜索摘要）" if item.get("search_only") and not item.get("ok") else ""
        lines.append(f"- [{title}]({url}){suffix}")
    return "\n".join(lines) if len(lines) > 1 else ""


def looks_like_bit_query(question: str) -> bool:
    query = re.sub(r"\s+", " ", str(question or "")).strip()
    if not query:
        return False
    normalized = normalize_text(query, compact=True)
    lowered = query.lower()

    if any(marker in query for marker in _OTHER_UNIVERSITY_MARKERS):
        return False

    other_school_match = re.search(r"([\u4e00-\u9fff]{2,12}(?:大学|学院))", query)
    if other_school_match and other_school_match.group(1) != "北京理工大学":
        return False

    explicit_bit = (
        "北京理工大学" in query
        or "北理工" in query
        or "bit.edu.cn" in lowered
        or re.search(r"\bbit\b", lowered) is not None
        or any(term in normalized for term in _BIT_QUERY_TERMS)
    )
    if explicit_bit:
        return True

    return any(term in normalized for term in _BIT_CONTEXT_TERMS)


def _build_search_query(question: str) -> str:
    query = re.sub(r"\s+", " ", str(question or "")).strip()
    if not query:
        return ""

    bit_scoped = looks_like_bit_query(query)
    normalized_query = normalize_text(query, compact=True)
    natural_language_query = any(token in normalized_query for token in ("有哪些", "什么", "怎么", "哪个", "是谁", "谁", "吗", "呢", "好吃"))
    if bit_scoped and not any(token in query for token in ("北京理工大学", "北理工", "bit.edu.cn", "BIT")):
        query = f"北京理工大学 {query}"

    keyword_terms = _query_keyword_terms(query)
    if not keyword_terms:
        return query

    concise_terms: List[str] = []
    seen = set()
    for term in keyword_terms:
        cleaned_term = term.strip()
        if len(cleaned_term) < 2 or cleaned_term in seen:
            continue
        seen.add(cleaned_term)
        concise_terms.append(cleaned_term)

    if any(token in normalized_query for token in ("好吃", "值得吃", "推荐", "美食")) and "推荐" not in concise_terms:
        concise_terms.append("推荐")

    if not concise_terms:
        return query

    prefix = "北京理工大学 " if bit_scoped else ""
    concise_query = f"{prefix}{' '.join(concise_terms[:4])}".strip()
    if concise_query and (natural_language_query or len(concise_query) + 4 < len(query)):
        return concise_query
    return query


def _query_tokens(query: str) -> List[str]:
    tokens = []
    for token in re.split(r"\s+", str(query or "")):
        token = token.strip().lower()
        if len(token) >= 2:
            tokens.append(token)
    return tokens[:10]


def _compact_text(text: str) -> str:
    return normalize_text(text, compact=True)


def _is_search_provider_host(host: str) -> bool:
    normalized = _normalize_host(host)
    if not normalized:
        return False
    if normalized in _SEARCH_PROVIDER_CONTENT_HOSTS:
        return False
    return any(normalized == suffix or normalized.endswith(f".{suffix}") for suffix in _SEARCH_PROVIDER_HOST_SUFFIXES)


def _is_search_provider_content_url(url: str) -> bool:
    parsed = urlparse(normalize_url(url))
    host = _normalize_host(parsed.netloc)
    return host in _SEARCH_PROVIDER_CONTENT_HOSTS


def _is_search_result_redirect_url(url: str) -> bool:
    parsed = urlparse(normalize_url(url))
    host = _normalize_host(parsed.netloc)
    return (host == "www.so.com" and parsed.path == "/link") or (host == "www.baidu.com" and parsed.path == "/link")


def _query_keyword_terms(query: str) -> List[str]:
    normalized = _compact_text(query)
    if not normalized:
        return []

    working = normalized
    for token in _QUERY_STOPWORDS:
        working = working.replace(token, " ")

    terms: List[str] = []
    seen = set()
    for match in re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", working):
        term = match.strip()
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms[:10]


def _score_search_candidate(title: str, snippet: str, host: str, query: str) -> int:
    corpus = " ".join([title or "", snippet or "", host or ""]).lower()
    score = 0

    if _is_preferred_official_host(host):
        score += 48
    elif host.endswith(".bit.edu.cn") or host == "bit.edu.cn":
        score += 40
    elif host.endswith(".edu.cn"):
        score += 26
    elif host.endswith(".gov.cn"):
        score += 20
    elif host.endswith(".edu"):
        score += 14
    else:
        score += 6

    for token in _query_tokens(query):
        if token in corpus:
            score += 6

    query_ngrams = char_ngrams(query, 2, compact=True)
    corpus_ngrams = char_ngrams(corpus, 2, compact=True)
    if query_ngrams and corpus_ngrams:
        score += min(24, len(query_ngrams & corpus_ngrams) * 2)

    compact_query = _compact_text(query)
    compact_corpus = _compact_text(corpus)
    if compact_query and compact_query in compact_corpus:
        score += 12

    for keyword in _query_keyword_terms(query):
        if keyword and keyword in compact_corpus:
            score += 14 if len(keyword) >= 2 else 0

    if host not in _SEARCH_PROVIDER_CONTENT_HOSTS and any(host.endswith(suffix) for suffix in _LOW_TRUST_HOST_SUFFIXES):
        score -= 8

    return score


def _clean_candidate_url(raw: str) -> str:
    text = html.unescape(str(raw or "")).replace("\\/", "/").replace("\\", "").strip()
    if text.startswith("//"):
        text = f"https:{text}"
    uddg_match = re.search(r"[?&]uddg=([^&]+)", text)
    if uddg_match:
        text = unquote(uddg_match.group(1))
    match = VALID_CANDIDATE_URL_PATTERN.match(text)
    if not match:
        return ""
    cleaned = match.group(0).rstrip(".,;:!?)]}，。；：！？】）》'")
    return normalize_url(cleaned)


def _extract_candidate_urls_from_search_page(text: str) -> List[str]:
    candidates: List[str] = []
    seen = set()
    patterns = [
        r'uddg=([^&\"]+)',
        r'"mu":"([^\"]+)"',
        r'"showurl":"([^\"]+)"',
        r'https?://[^\s\"\'>]+',
    ]

    for pattern in patterns:
        for raw in re.findall(pattern, text or ""):
            href = _clean_candidate_url(unquote(raw))
            if not href or href in seen:
                continue
            seen.add(href)
            candidates.append(href)

    return candidates


def _append_clean_candidate_url(candidates: List[str], seen: set, raw: str) -> None:
    href = _clean_candidate_url(unquote(str(raw or "")))
    if not href or href in seen:
        return
    seen.add(href)
    candidates.append(href)


def _collect_candidate_urls_from_json_blob(raw: str) -> List[str]:
    decoded = html.unescape(str(raw or "")).replace("\\/", "/").strip()
    if not decoded:
        return []

    candidates: List[str] = []
    seen = set()

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key or "").lower()
                if lowered in {"url", "mu", "pageurl", "originurl", "oriurl", "rawurl", "targeturl"}:
                    _append_clean_candidate_url(candidates, seen, item)
                elif isinstance(item, (dict, list)):
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    try:
        loaded = json.loads(decoded)
    except Exception:
        loaded = None

    if loaded is not None:
        walk(loaded)

    if candidates:
        return candidates

    for pattern in (
        r'"url"\s*:\s*"([^\"]+)"',
        r'"mu"\s*:\s*"([^\"]+)"',
        r'"targeturl"\s*:\s*"([^\"]+)"',
        r'"originurl"\s*:\s*"([^\"]+)"',
    ):
        for match in re.findall(pattern, decoded):
            _append_clean_candidate_url(candidates, seen, match)

    return candidates


def _collect_candidate_urls_from_node(
    node,
    direct_attrs: Tuple[str, ...] = (),
    json_attrs: Tuple[str, ...] = (),
    descendant_limit: int = 48,
) -> List[str]:
    candidates: List[str] = []
    seen = set()
    elements = [node]
    elements.extend(node.find_all(True, limit=descendant_limit))

    for element in elements:
        for attr_name in direct_attrs:
            raw_value = element.get(attr_name)
            if raw_value is None:
                continue
            if isinstance(raw_value, list):
                for item in raw_value:
                    _append_clean_candidate_url(candidates, seen, item)
            else:
                _append_clean_candidate_url(candidates, seen, raw_value)

        for attr_name in json_attrs:
            raw_value = element.get(attr_name)
            if not raw_value:
                continue
            for href in _collect_candidate_urls_from_json_blob(raw_value):
                _append_clean_candidate_url(candidates, seen, href)

    return candidates


def _pick_best_search_candidate_url(urls: List[str]) -> str:
    if not urls:
        return ""

    def priority(url: str) -> int:
        parsed = urlparse(url)
        host = _normalize_host(parsed.netloc)
        score = 0
        if _is_search_result_redirect_url(url):
            score -= 40
        elif _is_search_provider_content_url(url):
            score += 40
        elif not _is_search_provider_host(host):
            score += 30
        else:
            score += 10
        if url.startswith("https://"):
            score += 2
        if (parsed.path or "") not in {"", "/"}:
            score += 1
        return score

    _, best_url = max(enumerate(urls), key=lambda item: (priority(item[1]), -item[0]))
    return best_url


def _resolve_search_result_redirect_url(url: str) -> str:
    normalized = normalize_url(url)
    if not normalized or not _is_search_result_redirect_url(normalized):
        return normalized

    cached = _SEARCH_REDIRECT_CACHE.get(normalized)
    if cached:
        return cached

    resolved = normalized
    try:
        response = requests.head(
            normalized,
            headers=SEARCH_HEADERS,
            timeout=min(SEARCH_REDIRECT_TIMEOUT, WEB_SEARCH_TIMEOUT),
            allow_redirects=True,
        )
        candidate = normalize_url(response.url)
        if candidate:
            resolved = candidate
    except requests.RequestException:
        pass

    if resolved == normalized:
        try:
            response = requests.get(
                normalized,
                headers=SEARCH_HEADERS,
                timeout=min(SEARCH_REDIRECT_TIMEOUT, WEB_SEARCH_TIMEOUT),
                allow_redirects=True,
                stream=True,
            )
            candidate = normalize_url(response.url)
            response.close()
            if candidate:
                resolved = candidate
        except requests.RequestException:
            pass

    _SEARCH_REDIRECT_CACHE[normalized] = resolved
    return resolved


def _clean_search_candidate_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _build_search_candidate(title: str, url: str, snippet: str, rank: int) -> Optional[Dict]:
    cleaned_title = _clean_search_candidate_text(title)
    cleaned_url = _clean_candidate_url(url)
    if len(cleaned_title) < 4 or not cleaned_url:
        return None
    return {
        "title": cleaned_title,
        "url": cleaned_url,
        "snippet": _clean_search_candidate_text(snippet),
        "rank": rank,
    }


def _extract_search_candidates_from_duckduckgo(text: str) -> List[Dict]:
    soup = BeautifulSoup(text or "", "html.parser")
    results: List[Dict] = []
    for rank, node in enumerate(soup.select(".result"), start=1):
        link = node.select_one(".result__title a, .result__a")
        if not link:
            continue
        href = _clean_candidate_url(unquote(str(link.get("href") or "")))
        if not href:
            continue
        title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        snippet_node = node.select_one(".result__snippet")
        snippet = re.sub(r"\s+", " ", snippet_node.get_text(" ", strip=True)) if snippet_node else ""
        results.append({
            "title": title or _normalize_host(urlparse(href).netloc),
            "url": href,
            "snippet": snippet,
            "rank": rank,
        })
    return results


def _extract_search_candidates_from_baidu(text: str) -> List[Dict]:
    soup = BeautifulSoup(text or "", "html.parser")
    results: List[Dict] = []
    seen = set()
    for node in soup.select("div.c-container[tpl], div.result-op.c-container[tpl]"):
        title_link = node.select_one("h3 a")
        if not title_link:
            continue
        title = _clean_search_candidate_text(title_link.get_text(" ", strip=True))
        if len(title) < 4:
            continue

        href = _pick_best_search_candidate_url(
            _collect_candidate_urls_from_node(
                node,
                direct_attrs=("mu", "data-url", "data-landurl", "data-mdurl", "href"),
                json_attrs=("data-feedback", "data-ext"),
            )
        )
        if not href or href in seen:
            continue

        snippet = _clean_search_candidate_text(node.get_text(" ", strip=True))
        seen.add(href)
        candidate = _build_search_candidate(title or _normalize_host(urlparse(href).netloc), href, snippet, len(results) + 1)
        if candidate:
            results.append(candidate)

    if results:
        return results

    for rank, raw_href in enumerate(re.findall(r'"mu":"([^\"]+)"', text or ""), start=1):
        href = _clean_candidate_url(unquote(raw_href))
        if not href or href in seen:
            continue
        seen.add(href)
        results.append(
            {
                "title": _normalize_host(urlparse(href).netloc),
                "url": href,
                "snippet": href,
                "rank": rank,
            }
        )
    return results


def _extract_search_candidates_from_so360(text: str) -> List[Dict]:
    soup = BeautifulSoup(text or "", "html.parser")
    results: List[Dict] = []
    seen = set()

    for node in soup.select("li.res-list"):
        link = node.select_one("h3.res-title a")
        if not link:
            continue
        href = _pick_best_search_candidate_url(
            _collect_candidate_urls_from_node(
                node,
                direct_attrs=("data-mdurl", "href"),
                json_attrs=(),
            )
        )
        if not href or href in seen:
            continue

        title = _clean_search_candidate_text(link.get_text(" ", strip=True))
        if len(title) < 4:
            continue

        snippet = _clean_search_candidate_text(node.get_text(" ", strip=True))
        seen.add(href)
        candidate = _build_search_candidate(title, href, snippet, len(results) + 1)
        if candidate:
            results.append(candidate)
    return results


def _extract_search_candidates(provider: str, text: str) -> List[Dict]:
    if provider == "duckduckgo":
        parsed = _extract_search_candidates_from_duckduckgo(text)
        if parsed:
            return parsed
    if provider == "so360":
        parsed = _extract_search_candidates_from_so360(text)
        if parsed:
            return parsed
    if provider == "baidu":
        parsed = _extract_search_candidates_from_baidu(text)
        if parsed:
            return parsed

    fallback: List[Dict] = []
    for rank, href in enumerate(_extract_candidate_urls_from_search_page(text), start=1):
        fallback.append(
            {
                "title": _normalize_host(urlparse(href).netloc),
                "url": href,
                "snippet": href,
                "rank": rank,
            }
        )
    return fallback


def _fetch_search_provider(provider: str, search_url: str) -> Dict:
    try:
        response = requests.get(
            search_url,
            headers=SEARCH_HEADERS,
            timeout=WEB_SEARCH_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
        decoded_text = _decode_response_text(response)
        if provider == "baidu" and (
            "wappass.baidu.com/static/captcha/" in str(response.url)
            or any(token in decoded_text for token in ("请输入以下验证码", "百度安全验证", "网络不给力，请稍后重试"))
        ):
            return {
                "provider": provider,
                "search_url": search_url,
                "candidates": [],
                "error": "触发 Baidu 验证码页",
            }
        if provider == "so360" and "qcaptcha.so.com" in str(response.url) and "访问异常页面" in decoded_text:
            return {
                "provider": provider,
                "search_url": search_url,
                "candidates": [],
                "error": "触发 360 验证码页",
            }
        return {
            "provider": provider,
            "search_url": search_url,
            "candidates": _extract_search_candidates(provider, decoded_text),
            "error": "",
        }
    except Exception as exc:
        return {
            "provider": provider,
            "search_url": search_url,
            "candidates": [],
            "error": str(exc),
        }


def search_public_web(question: str) -> Dict:
    if not WEB_SEARCH_ENABLED:
        return {
            "query": "",
            "results": [],
            "steps": [{"stage": "web_search", "ok": False, "message": "全网搜索已关闭", "url": ""}],
        }

    query = _build_search_query(question)
    if not query:
        return {
            "query": "",
            "results": [],
            "steps": [{"stage": "web_search", "ok": False, "message": "搜索词为空，未执行全网搜索", "url": ""}],
        }

    steps = [{"stage": "web_search", "ok": True, "message": f"已启动全网搜索：{query}", "url": ""}]

    candidates: List[Dict] = []
    seen = set()
    enough_candidates_threshold = max(WEB_SEARCH_MAX_RESULTS, WEB_SEARCH_FETCH_LIMIT * 2)
    providers = {
        "so360": WEB_SEARCH_SO360_URL.format(query=quote_plus(query)),
        "baidu": WEB_SEARCH_BAIDU_URL.format(query=quote_plus(query)),
    }

    provider_order = {provider: index for index, provider in enumerate(providers.keys())}
    provider_results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        future_map = {
            executor.submit(_fetch_search_provider, provider, search_url): provider
            for provider, search_url in providers.items()
        }
        for future in as_completed(future_map):
            provider_results.append(future.result())

    provider_results.sort(key=lambda item: provider_order.get(str(item.get("provider") or ""), 0))

    for result in provider_results:
        provider = str(result.get("provider") or "")
        search_url = str(result.get("search_url") or "")
        if result.get("error"):
            steps.append({"stage": "web_search", "ok": False, "message": f"{provider} 搜索请求失败: {result['error']}", "url": search_url})
            continue

        provider_candidates = result.get("candidates") or []
        added = 0
        for item in provider_candidates:
            href = _clean_candidate_url(str(item.get("url") or ""))
            if not href or href in seen:
                continue

            candidate_url = _resolve_search_result_redirect_url(href) if _is_search_result_redirect_url(href) else href
            candidate_host = _normalize_host(urlparse(candidate_url).netloc)
            if not candidate_host or "." not in candidate_host or (_is_search_provider_host(candidate_host) and not _is_search_result_redirect_url(candidate_url) and not _is_search_provider_content_url(candidate_url)):
                continue
            if _is_restricted_host(candidate_host):
                continue

            safe, _ = is_safe_public_url(candidate_url)
            if not safe:
                continue

            title = str(item.get("title") or candidate_host)
            snippet = str(item.get("snippet") or candidate_url)
            score = _score_search_candidate(
                title,
                snippet,
                "" if (_is_search_result_redirect_url(candidate_url) and not _is_search_provider_content_url(candidate_url)) else candidate_host,
                query,
            )
            if _is_search_result_redirect_url(candidate_url):
                score += 12
            if _is_search_provider_content_url(candidate_url):
                score += 6
            if candidate_url != href and not _is_search_result_redirect_url(candidate_url):
                score += 8
            if score < 20:
                continue

            seen.add(candidate_url)
            candidates.append(
                {
                    "title": title,
                    "url": candidate_url,
                    "host": candidate_host,
                    "snippet": snippet,
                    "rank": int(item.get("rank") or (len(candidates) + 1)),
                    "score": score,
                }
            )
            added += 1

        steps.append({"stage": "web_search", "ok": True, "message": f"{provider} 提取到 {added} 个候选网址", "url": search_url})
        if len(candidates) >= enough_candidates_threshold:
            steps.append({"stage": "web_search", "ok": True, "message": f"候选网页已足够，提前结束后续搜索（{len(candidates)} 个）", "url": ""})
            break

    candidates.sort(key=lambda item: (-int(item.get("score") or 0), int(item.get("rank") or 0)))
    preferred_results = [item for item in candidates if _is_preferred_official_host(str(item.get("host") or ""))]
    other_results = [item for item in candidates if not _is_preferred_official_host(str(item.get("host") or ""))]
    top_results = (preferred_results + other_results)[:WEB_SEARCH_MAX_RESULTS]
    steps.append({"stage": "web_search", "ok": True, "message": f"全网搜索获得 {len(top_results)} 个候选网页", "url": ""})
    return {"query": query, "results": top_results, "steps": steps}


def search_and_fetch_public_web(question: str, exclude_hosts: Optional[List[str]] = None) -> Dict:
    search_bundle = search_public_web(question)
    steps = list(search_bundle.get("steps") or [])
    excluded = {str(host or "").lower() for host in (exclude_hosts or [])}

    candidates = []
    for item in search_bundle.get("results") or []:
        host = str(item.get("host") or "").lower()
        if host and host in excluded:
            continue
        candidates.append(item)

    if not candidates:
        steps.append({"stage": "web_search", "ok": False, "message": "没有可抓取的全网候选网页", "url": ""})
        return {"query": search_bundle.get("query") or "", "results": [], "steps": steps}

    subjective_query = _should_keep_third_party_web_results(question)
    if subjective_query:
        authoritative_candidates = [item for item in candidates if _is_authoritative_public_host(str(item.get("host") or ""))]
        fetch_plan = authoritative_candidates[: min(2, len(authoritative_candidates))]
        if not fetch_plan:
            fetch_plan = candidates[: min(len(candidates), WEB_SEARCH_FETCH_LIMIT)]
    else:
        fetch_plan = candidates[: min(len(candidates), max(WEB_SEARCH_FETCH_LIMIT * 2, WEB_SEARCH_FETCH_LIMIT))]
    steps.append({"stage": "web_search", "ok": True, "message": f"准备并行抓取候选网页，目标获取 {min(WEB_SEARCH_FETCH_LIMIT, len(fetch_plan))} 个有效结果", "url": ""})
    fetched_results: List[Dict] = []
    success_count = 0
    consumed_urls = {str(item.get("url") or "") for item in fetch_plan if item.get("url")}
    ordered_fetches: List[Tuple[int, Dict, Dict]] = []

    with ThreadPoolExecutor(max_workers=min(WEB_FETCH_CONCURRENCY, len(fetch_plan) or 1)) as executor:
        future_map = {
            executor.submit(
                fetch_public_web_url,
                str(item.get("url") or ""),
                title=str(item.get("title") or ""),
                snippet=str(item.get("snippet") or ""),
            ): (index, item)
            for index, item in enumerate(fetch_plan)
        }
        for future in as_completed(future_map):
            index, item = future_map[future]
            fetched = future.result()
            ordered_fetches.append((index, item, fetched))

    ordered_fetches.sort(key=lambda entry: entry[0])
    for _, item, fetched in ordered_fetches:
        if fetched.get("ok"):
            fetched["search_rank"] = item.get("rank")
            fetched["search_score"] = item.get("score")
            fetched["search_snippet"] = str(item.get("snippet") or "")
            if success_count >= WEB_SEARCH_FETCH_LIMIT:
                steps.extend(fetched.get("steps") or [])
                continue
            success_count += 1
        fetched_results.append(fetched)
        steps.extend(fetched.get("steps") or [])

    supplemental_results: List[Dict] = []
    if success_count < WEB_SEARCH_FETCH_LIMIT:
        for item in candidates:
            url = str(item.get("url") or "")
            snippet = re.sub(r"\s+", " ", str(item.get("snippet") or "")).strip()
            if not url or url in consumed_urls or len(snippet) < MIN_WEB_CONTENT_LENGTH:
                continue
            supplemental_results.append(
                {
                    "ok": False,
                    "search_only": True,
                    "url": url,
                    "final_url": url,
                    "title": str(item.get("title") or url),
                    "site": {"name": str(item.get("title") or url), "host": str(item.get("host") or "")},
                    "excerpt": snippet[:360],
                    "search_snippet": snippet,
                    "search_score": item.get("score"),
                    "search_rank": item.get("rank"),
                    "steps": [],
                }
            )
            if len(supplemental_results) >= 2:
                break

    all_results = fetched_results + supplemental_results
    authoritative_success = any(
        item.get("ok")
        and _is_authoritative_public_host(
            _normalize_host(urlparse(str(item.get("final_url") or item.get("url") or "")).netloc)
        )
        for item in all_results
    )
    if authoritative_success and not _should_keep_third_party_web_results(question):
        all_results = [
            item
            for item in all_results
            if _is_authoritative_public_host(
                _normalize_host(urlparse(str(item.get("final_url") or item.get("url") or "")).netloc)
            )
        ]

    return {
        "query": search_bundle.get("query") or "",
        "results": all_results,
        "steps": steps,
    }


