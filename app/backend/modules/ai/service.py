import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import requests

from modules.ai.kb import index_status, query_index
from modules.ai.official_sites import load_official_site_entries
from modules.ai.web_fetcher import (
    build_web_reference,
    format_web_sources_markdown,
    looks_like_bit_query,
    search_and_fetch_public_web,
)
from modules.shared.paths import DATA_ROOT
from modules.shared.text_utils import lexical_score, normalize_text

logger = logging.getLogger(__name__)

FAQ_PATH = DATA_ROOT / "faq.md"
OFFICIAL_SITE_GUIDE_SOURCE = "19_官方网址与办事入口.md"
OFFICIAL_SITE_QUERY_TERMS = (
    "网址",
    "网站",
    "官网",
    "入口",
    "链接",
    "哪里查",
    "去哪查",
    "在哪查",
    "哪里看",
    "在哪看",
    "去哪里看",
    "哪个网站",
    "哪个网址",
    "什么网站",
    "什么网址",
    "官网入口",
    "网站入口",
)
OFFICIAL_SITE_CORE_HOSTS = (
    "www.bit.edu.cn",
    "hi.bit.edu.cn",
    "ehall.bit.edu.cn",
    "jwc.bit.edu.cn",
    "student.bit.edu.cn",
    "itc.bit.edu.cn",
)

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "replace_with_your_model")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

LLM_BASE_URL = DEEPSEEK_BASE_URL if DEEPSEEK_API_KEY else OPENAI_BASE_URL
LLM_API_KEY = DEEPSEEK_API_KEY or OPENAI_API_KEY
LLM_MODEL = DEEPSEEK_MODEL if DEEPSEEK_API_KEY else OPENAI_MODEL
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "15"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_TOP_P = float(os.getenv("LLM_TOP_P", "0.9"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "400"))
LLM_MIN_CONFIDENCE = float(os.getenv("LLM_MIN_CONFIDENCE", "0.60"))
KB_PREFERRED_MIN_SCORE = float(os.getenv("KB_PREFERRED_MIN_SCORE", "0.55"))
WEB_FETCH_ENABLED = os.getenv("WEB_FETCH_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
KB_REFERENCE_LIMIT = max(4, int(os.getenv("KB_REFERENCE_LIMIT", "8")))
KB_RETRIEVE_CANDIDATE_K = max(KB_REFERENCE_LIMIT, int(os.getenv("KB_RETRIEVE_CANDIDATE_K", "18")))
KB_REFERENCE_MIN_SCORE = max(0.0, float(os.getenv("KB_REFERENCE_MIN_SCORE", "0.22")))
KB_REFERENCE_SCORE_MARGIN = max(0.0, float(os.getenv("KB_REFERENCE_SCORE_MARGIN", "0.18")))
KB_REFERENCE_SCORE_RATIO = min(1.0, max(0.0, float(os.getenv("KB_REFERENCE_SCORE_RATIO", "0.72"))))
KB_REFERENCE_MAX_PER_SOURCE = max(1, int(os.getenv("KB_REFERENCE_MAX_PER_SOURCE", "2")))
FAQ_MATCH_MIN_SCORE = max(0.0, float(os.getenv("FAQ_MATCH_MIN_SCORE", "0.22")))
FAQ_PROMOTION_MIN_SCORE = max(FAQ_MATCH_MIN_SCORE, float(os.getenv("FAQ_PROMOTION_MIN_SCORE", "0.60")))
FAQ_PROMOTION_SCORE_MARGIN = max(0.0, float(os.getenv("FAQ_PROMOTION_SCORE_MARGIN", "0.06")))

_LIVE_WEB_SIGNAL_TERMS = (
    "最新",
    "当前",
    "目前",
    "今天",
    "今日",
    "近期",
    "今年",
    "本周",
    "本月",
    "什么时候",
    "何时",
    "时间",
    "开放时间",
    "开馆",
    "开放",
    "截止",
    "截止时间",
    "通知",
    "公告",
    "发布",
    "更新",
    "入口",
    "链接",
    "网址",
    "网站",
)

_REFERENCE_FOCUS_STOPWORDS = (
    "北京理工大学",
    "北理工",
    "bit",
    "学校",
    "新生",
    "同学",
    "请问",
    "一下",
    "这个",
    "那个",
    "一般",
    "怎么",
    "如何",
    "什么",
    "哪个",
    "哪一个",
    "怎么办",
    "吗",
    "呢",
    "呀",
    "啊",
    "我",
    "想",
    "从",
    "去",
    "到",
    "先",
    "后",
)

_REFERENCE_FOCUS_TERMS = (
    "绿色通道",
    "助学贷款",
    "助学金",
    "奖学金",
    "统一身份认证",
    "统一身份",
    "信息化服务大厅",
    "智慧北理",
    "迎新网",
    "中关村",
    "良乡",
    "校车",
    "班车",
    "地铁",
    "选课",
    "补退选",
    "培养方案",
    "教学日历",
    "图书馆",
    "开馆时间",
    "开放时间",
    "食堂",
    "宿舍",
    "断电",
    "断网",
    "校医院",
    "医保",
    "报销",
    "校园卡",
    "挂失",
    "充值",
    "校园网",
    "webvpn",
    "vpn",
    "报到",
    "材料",
    "体测",
    "转专业",
    "缓考",
)

_UNBACKED_COMPARISON_TERMS = (
    "免费",
    "低成本",
    "更便捷",
    "更省心",
    "班次密集",
    "直达",
    "减少换乘",
    "客流影响",
    "时间可控",
    "更可靠",
    "更经济",
    "更灵活",
    "更省时",
)

_CHOICE_QUESTION_MARKERS = (
    "怎么选",
    "如何选",
    "选哪个",
    "先办哪个",
    "先选哪个",
)

_DECISION_SUPPORT_MARKERS = (
    "优先",
    "先行",
    "先办理",
    "先完成",
    "先处理",
    "办理后",
    "入学后",
    "报到后",
    "再申请",
    "再办理",
    "随后申请",
    "之后申请",
)

_KB_ANSWER_WEB_FALLBACK_MARKERS = (
    "无法确定",
    "未包含",
    "未提到",
    "未列出具体",
    "未提供具体",
    "没有明确说明",
    "未给出具体",
    "建议您通过",
    "建议通过",
    "建议查阅",
    "建议查询",
    "建议入学后",
    "建议亲自",
)


def should_fetch_public_web(question: str, bit_scoped_question: bool, kb_confident: bool) -> bool:
    if not WEB_FETCH_ENABLED:
        return False

    if not bit_scoped_question:
        return True

    if not kb_confident:
        return True

    normalized = normalize_text(question)
    return any(token in normalized for token in _LIVE_WEB_SIGNAL_TERMS)


def _kb_answer_needs_web_followup(answer: str) -> bool:
    normalized_answer = normalize_text(answer, compact=True)
    if not normalized_answer:
        return True

    return any(
        normalize_text(marker, compact=True) in normalized_answer
        for marker in _KB_ANSWER_WEB_FALLBACK_MARKERS
    )


def load_faq() -> List[Tuple[str, str]]:
    if not FAQ_PATH.exists():
        return []

    content = FAQ_PATH.read_text(encoding="utf-8")
    rows: List[Tuple[str, str]] = []
    question, answer = "", ""

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("Q:"):
            question = line[2:].strip()
        elif line.startswith("A:"):
            answer = line[2:].strip()
            if question and answer:
                rows.append((question, answer))
                question, answer = "", ""

    return rows


def score_question(input_question: str, faq_question: str) -> float:
    return lexical_score(input_question, faq_question, bidirectional_contains=True)


def _find_best_faq_match(user_question: str) -> Optional[Dict]:
    faq_pairs = load_faq()
    if not faq_pairs:
        return None

    best_score = 0.0
    best_question = ""
    best_answer = ""
    for question, answer in faq_pairs:
        score = score_question(user_question, question)
        if score > best_score:
            best_score = score
            best_question = question
            best_answer = answer

    if best_score < FAQ_MATCH_MIN_SCORE or not best_answer:
        return None

    return {
        "question": best_question,
        "answer": best_answer,
        "score": float(best_score),
    }


def _make_faq_reference_result(faq_match: Optional[Dict]) -> Optional[Dict]:
    if not faq_match:
        return None
    return {
        "score": float(faq_match.get("score") or 0.0),
        "source": "faq.md",
        "chunk_id": -1,
        "text": f"Q:{faq_match.get('question') or ''} A:{faq_match.get('answer') or ''}",
        "match_type": "faq_pair",
    }


def _reference_result_score(item: Optional[Dict]) -> float:
    return float((item or {}).get("score") or 0.0)


def _reference_text_signature(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _extract_focus_ngrams(question: str) -> List[str]:
    compact_question = normalize_text(question, compact=True)
    if not compact_question:
        return []

    terms: List[str] = []
    seen = set()
    for term in _REFERENCE_FOCUS_TERMS:
        normalized_term = normalize_text(term, compact=True)
        if normalized_term and normalized_term in compact_question and normalized_term not in seen:
            seen.add(normalized_term)
            terms.append(normalized_term)

    if terms:
        return terms

    for token in _REFERENCE_FOCUS_STOPWORDS:
        compact_question = compact_question.replace(token, "")

    compact_question = compact_question.strip()
    if len(compact_question) < 2:
        return []
    return [compact_question]


def _reference_focus_score(user_question: str, text: str) -> float:
    focus_ngrams = _extract_focus_ngrams(user_question)
    normalized_text = normalize_text(text, compact=True)
    if not focus_ngrams or not normalized_text:
        return 0.0

    total_weight = 0.0
    hit_weight = 0.0
    for gram in focus_ngrams:
        weight = float(len(gram))
        total_weight += weight
        if gram in normalized_text:
            hit_weight += weight
    if total_weight <= 0:
        return 0.0
    return min(1.0, hit_weight / total_weight)


def _extract_reference_prompts(text: str) -> List[str]:
    raw_text = _reference_text_signature(text)
    if not raw_text:
        return []
    prompts = [match.strip(" /") for match in re.findall(r"Q:\s*(.*?)(?=\s*A:|\s*/\s*Q:|$)", raw_text)]
    return [prompt for prompt in prompts if prompt]


def _annotate_reference_priority(user_question: str, item: Dict) -> Dict:
    annotated = dict(item)
    prompt_score = 0.0
    for prompt in _extract_reference_prompts(item.get("text") or ""):
        prompt_score = max(prompt_score, score_question(user_question, prompt))

    prompt_bonus = min(0.12, prompt_score * 0.15)
    focus_score = _reference_focus_score(user_question, item.get("text") or "")
    focus_bonus = min(0.24, focus_score * 0.24)

    annotated["prompt_score"] = float(prompt_score)
    annotated["focus_score"] = float(focus_score)
    annotated["priority_score"] = float(_reference_result_score(item) + prompt_bonus + focus_bonus)
    return annotated


def _is_redundant_reference(candidate: Dict, selected: Dict) -> bool:
    if str(candidate.get("source") or "") != str(selected.get("source") or ""):
        return False

    candidate_text = _reference_text_signature(candidate.get("text") or "")
    selected_text = _reference_text_signature(selected.get("text") or "")
    if not candidate_text or not selected_text:
        return False

    if candidate_text in selected_text or selected_text in candidate_text:
        return True

    similarity = lexical_score(candidate_text, selected_text)
    candidate_chunk_id = int(candidate.get("chunk_id", -10**9))
    selected_chunk_id = int(selected.get("chunk_id", -10**9))
    if similarity >= 0.84:
        return True
    if candidate_chunk_id >= 0 and selected_chunk_id >= 0 and abs(candidate_chunk_id - selected_chunk_id) <= 1 and similarity >= 0.68:
        return True
    return False


def _should_promote_faq_match(faq_match: Optional[Dict], kb_results: List[Dict]) -> bool:
    if not faq_match:
        return False

    faq_score = float(faq_match.get("score") or 0.0)
    if not kb_results:
        return faq_score >= FAQ_MATCH_MIN_SCORE

    top_kb_score = _reference_result_score(kb_results[0])
    return faq_score >= max(FAQ_PROMOTION_MIN_SCORE, top_kb_score - FAQ_PROMOTION_SCORE_MARGIN)


def _select_reference_results(user_question: str, kb_results: List[Dict], faq_match: Optional[Dict], limit: int = KB_REFERENCE_LIMIT) -> List[Dict]:
    ranked_results = [
        _annotate_reference_priority(user_question, item)
        for item in kb_results
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    top_kb_score = max((_reference_result_score(item) for item in ranked_results), default=0.0)
    ranked_results.sort(
        key=lambda item: (
            float(item.get("priority_score") or 0.0),
            float(item.get("focus_score") or 0.0),
            _reference_result_score(item),
            float(item.get("prompt_score") or 0.0),
        ),
        reverse=True,
    )
    score_floor = max(KB_REFERENCE_MIN_SCORE, top_kb_score * KB_REFERENCE_SCORE_RATIO, top_kb_score - KB_REFERENCE_SCORE_MARGIN) if ranked_results else KB_REFERENCE_MIN_SCORE

    promote_faq = _should_promote_faq_match(faq_match, ranked_results)
    faq_result = _make_faq_reference_result(faq_match) if promote_faq else None

    selected: List[Dict] = []
    per_source_counts: Dict[str, int] = {}

    def append_result(item: Dict) -> None:
        source = str(item.get("source") or "unknown.md")
        selected.append(item)
        per_source_counts[source] = per_source_counts.get(source, 0) + 1

    if faq_result is not None:
        append_result(faq_result)

    for item in ranked_results:
        if len(selected) >= limit:
            break
        if selected and _reference_result_score(item) < score_floor and float(item.get("prompt_score") or 0.0) < 0.35:
            continue

        source = str(item.get("source") or "unknown.md")
        if faq_result is not None and source == "faq.md":
            continue
        if per_source_counts.get(source, 0) >= KB_REFERENCE_MAX_PER_SOURCE:
            continue
        if any(_is_redundant_reference(item, existing) for existing in selected):
            continue
        append_result(item)

    if not selected and faq_match:
        faq_only_result = _make_faq_reference_result(faq_match)
        if faq_only_result is not None:
            return [faq_only_result]
    if not selected and ranked_results:
        return [ranked_results[0]]
    return selected[:limit]


def _trim_trailing_punct(text) -> str:
    return str(text or "").strip().rstrip("。；;,. ")


def _looks_like_official_site_query(user_question: str) -> bool:
    normalized_question = normalize_text(user_question)
    lowered_question = str(user_question or "").lower()
    if ".bit.edu.cn" in lowered_question or lowered_question.startswith("http"):
        return True
    return any(term in normalized_question for term in OFFICIAL_SITE_QUERY_TERMS)


def _score_official_site_entry(user_question: str, entry: Dict) -> float:
    normalized_question = normalize_text(user_question)
    lowered_question = str(user_question or "").lower()
    haystack = " ".join(
        [
            str(entry.get("name") or ""),
            str(entry.get("host") or ""),
            str(entry.get("root_url") or ""),
            str(entry.get("category") or ""),
            str(entry.get("summary") or ""),
            *[str(item) for item in (entry.get("aliases") or [])],
            *[str(item) for item in (entry.get("scenes") or [])],
        ]
    )
    score = lexical_score(user_question, haystack, bidirectional_contains=True)
    bonus = 0.0

    host = str(entry.get("host") or "")
    if host and host in lowered_question:
        bonus += 0.45
    if str(entry.get("root_url") or "").lower() in lowered_question:
        bonus += 0.45
    if str(entry.get("name") or "") in user_question:
        bonus += 0.22

    alias_hits = 0
    for alias in entry.get("aliases") or []:
        token = normalize_text(alias)
        if token and token in normalized_question:
            alias_hits += 1
    bonus += min(0.24, alias_hits * 0.08)

    scene_hits = 0
    for scene in entry.get("scenes") or []:
        token = normalize_text(scene)
        if token and token in normalized_question:
            scene_hits += 1
    bonus += min(0.30, scene_hits * 0.10)

    scenario_boosts = {
        "www.bit.edu.cn": ("学校", "官网", "通知", "公告", "部门"),
        "hi.bit.edu.cn": ("迎新", "报到", "新生", "材料", "到校"),
        "ehall.bit.edu.cn": ("智慧北理", "缴费", "校园卡", "办事", "申请"),
        "sso.bit.edu.cn": ("统一身份", "统一认证", "密码", "登录", "账号"),
        "jwc.bit.edu.cn": ("选课", "成绩", "培养方案", "学籍", "教学日历"),
        "jxzx.bit.edu.cn": ("缓考", "考试", "考务", "转专业"),
        "student.bit.edu.cn": ("奖学金", "助学金", "资助", "绿色通道", "助学贷款", "勤工助学"),
        "itc.bit.edu.cn": ("校园网", "网络", "vpn", "正版软件", "邮箱", "信息化", "统一认证"),
        "webvpn.bit.edu.cn": ("webvpn", "校外访问", "远程访问", "数据库"),
        "lib.bit.edu.cn": ("图书馆", "数据库", "借书", "座位", "续借"),
        "xyy.bit.edu.cn": ("校医院", "医保", "报销", "转诊", "门诊", "体检"),
        "cwc.bit.edu.cn": ("学费", "住宿费", "缴费", "收费", "财务"),
        "job.bit.edu.cn": ("就业", "招聘", "实习", "宣讲会"),
        "international.bit.edu.cn": ("国际交流", "交换", "海外学习", "联合培养", "港澳台"),
        "isc.bit.edu.cn": ("国际学生", "留学生", "签证", "住宿", "国际学生招生"),
        "admission.bit.edu.cn": ("本科招生", "录取", "通知书", "招生"),
        "grd.bit.edu.cn": ("研究生", "研招", "研究生招生"),
    }
    for keyword in scenario_boosts.get(host, ()):
        token = normalize_text(keyword)
        if token and token in normalized_question:
            bonus += 0.10

    if entry.get("restricted") and any(term in normalized_question for term in ("登录", "入口", "办事", "认证")):
        bonus += 0.05
    if not entry.get("restricted") and any(term in normalized_question for term in ("公告", "通知", "查询")):
        bonus += 0.03

    return min(0.995, score + bonus)


def _select_core_official_sites(catalog: List[Dict]) -> List[Dict]:
    index_by_host = {str(item.get("host") or ""): item for item in catalog}
    results: List[Dict] = []
    for offset, host in enumerate(OFFICIAL_SITE_CORE_HOSTS):
        entry = index_by_host.get(host)
        if not entry:
            continue
        enriched = dict(entry)
        enriched["score"] = round(0.82 - offset * 0.04, 3)
        results.append(enriched)
    return results


def build_official_site_reference(matches: List[Dict]) -> str:
    parts = []
    for item in matches[:4]:
        scene_text = "、".join(item.get("scenes") or []) or str(item.get("category") or "相关业务")
        access = str(item.get("access") or ("通常需要统一身份认证登录" if item.get("restricted") else "公开访问"))
        parts.append(
            f"(来源:{OFFICIAL_SITE_GUIDE_SOURCE} score:{float(item.get('score') or 0.0):.3f}) "
            f"名称：{item.get('name')}；网址：{item.get('root_url')}；用途：{_trim_trailing_punct(item.get('summary'))}；"
            f"适合查询：{_trim_trailing_punct(scene_text)}；访问说明：{_trim_trailing_punct(access)}。"
        )
    return "\n\n".join(parts)


def build_official_site_answer(matches: List[Dict], markdown: bool = False) -> str:
    entries = [item for item in matches if isinstance(item, dict)]
    if not entries:
        return ""

    if markdown:
        lines = ["## 推荐入口"]
        for item in entries[:4]:
            scene_text = "、".join(item.get("scenes") or []) or str(item.get("category") or "相关业务")
            access = str(item.get("access") or ("通常需要统一身份认证登录" if item.get("restricted") else "公开访问"))
            lines.append(
                f"- {item.get('name')}：[{item.get('root_url')}]({item.get('root_url')})。"
                f"用途：{_trim_trailing_punct(item.get('summary'))}。适合查询：{_trim_trailing_punct(scene_text)}。访问说明：{_trim_trailing_punct(access)}。"
            )
        lines.append("")
        lines.append("## 使用建议")
        lines.append("- 如果这是登录类入口，先确认统一身份认证账号和密码可用。")
        lines.append("- 如果还不确定从哪个入口开始，可先从学校官网或智慧北理进入，再跳转到对应业务站点。")
        lines.append("")
        lines.append("### 来源")
        lines.append(f"- {OFFICIAL_SITE_GUIDE_SOURCE} ({float(entries[0].get('score') or 0.0):.3f})")
        return "\n".join(lines)

    parts = []
    for item in entries[:4]:
        scene_text = "、".join(item.get("scenes") or []) or str(item.get("category") or "相关业务")
        access = str(item.get("access") or ("通常需要统一身份认证登录" if item.get("restricted") else "公开访问"))
        parts.append(
            f"{item.get('name')}：{item.get('root_url')}。用途：{_trim_trailing_punct(item.get('summary'))}。"
            f"适合查询：{_trim_trailing_punct(scene_text)}。访问说明：{_trim_trailing_punct(access)}。"
        )
    return "\n".join(parts) + f"\n\n【来源: {OFFICIAL_SITE_GUIDE_SOURCE} ({float(entries[0].get('score') or 0.0):.3f})】"


def retrieve_official_site_bundle(user_question: str) -> Dict:
    catalog = load_official_site_entries()
    if not catalog or not _looks_like_official_site_query(user_question):
        return {"reference_text": "", "top_score": 0.0, "results": [], "backend": "none"}

    matches: List[Dict] = []
    for entry in catalog:
        score = _score_official_site_entry(user_question, entry)
        if score < 0.20:
            continue
        enriched = dict(entry)
        enriched["score"] = score
        matches.append(enriched)

    matches.sort(key=lambda item: (float(item.get("score") or 0.0), 1 if not item.get("restricted") else 0), reverse=True)
    if not matches or float(matches[0].get("score") or 0.0) < 0.34:
        matches = _select_core_official_sites(catalog)

    top_matches = matches[:4]
    if not top_matches:
        return {"reference_text": "", "top_score": 0.0, "results": [], "backend": "none"}

    return {
        "reference_text": build_official_site_reference(top_matches),
        "top_score": float(top_matches[0].get("score") or 0.0),
        "results": top_matches,
        "backend": "official_site_catalog",
    }


def extract_sources(reference_text: str) -> List[Tuple[str, str]]:
    matches = re.findall(r"\(来源:([^\s\)]+)\s+score:([0-9.]+)\)", reference_text or "")
    return [(match[0], match[1]) for match in matches]


def format_sources_markdown(reference_text: str) -> str:
    return _build_source_block(reference_text=reference_text, markdown=True)


def _extract_kb_source_labels(reference_text: str) -> List[str]:
    labels: List[str] = []
    seen = set()
    for source, score in extract_sources(reference_text):
        key = (source, score)
        if key in seen:
            continue
        seen.add(key)
        labels.append(f"{source} ({score})")
    return labels


def _extract_web_source_items(web_sources: Optional[List[Dict]] = None) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    seen = set()
    for item in web_sources or []:
        if not item.get("ok"):
            continue
        url = str(item.get("final_url") or item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        title = str(item.get("title") or item.get("site", {}).get("name") or url)
        items.append((title, url))
    return items


def _build_source_block(
    reference_text: str = "",
    web_sources: Optional[List[Dict]] = None,
    markdown: bool = False,
    label_kb: bool = False,
) -> str:
    kb_labels = _extract_kb_source_labels(reference_text)
    web_items = _extract_web_source_items(web_sources)

    if markdown:
        lines = ["### 来源"]
        for label in kb_labels:
            prefix = "知识库：" if label_kb else ""
            lines.append(f"- {prefix}{label}")
        for title, url in web_items:
            lines.append(f"- 网页：[{title}]({url})")
        return "\n".join(lines) if len(lines) > 1 else ""

    labels = list(kb_labels)
    labels.extend(url for _, url in web_items)
    if not labels:
        return ""
    return f"【来源: {'；'.join(labels)}】"


def append_sources_if_missing(
    answer: str,
    reference_text: str = "",
    web_sources: Optional[List[Dict]] = None,
    markdown: bool = False,
    label_kb: bool = False,
) -> str:
    if not answer:
        return answer
    if "【来源:" in answer or "### 来源" in answer:
        return answer

    source_block = _build_source_block(
        reference_text=reference_text,
        web_sources=web_sources,
        markdown=markdown,
        label_kb=label_kb,
    )
    if not source_block:
        return answer
    return f"{answer.rstrip()}\n\n{source_block}"


def call_llm(messages: List[Dict[str, str]]) -> str:
    if not LLM_BASE_URL or not LLM_API_KEY:
        return ""

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "top_p": LLM_TOP_P,
        "max_tokens": LLM_MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=OPENAI_TIMEOUT,
        )
        if response.status_code != 200:
            logger.warning("LLM request failed: status=%s body=%s", response.status_code, response.text[:300])
            return ""
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.RequestException as exc:
        logger.warning("LLM request exception: %s", exc)
        return ""
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("LLM response parse error: %s", exc)
        return ""


def _find_unbacked_comparison_terms(answer: str, reference_text: str) -> List[str]:
    normalized_answer = normalize_text(answer, compact=True)
    normalized_reference = normalize_text(reference_text, compact=True)
    if not normalized_answer or not normalized_reference:
        return []

    findings: List[str] = []
    for term in _UNBACKED_COMPARISON_TERMS:
        normalized_term = normalize_text(term, compact=True)
        if normalized_term and normalized_term in normalized_answer and normalized_term not in normalized_reference:
            findings.append(term)
    return findings


def _build_grounded_fallback_answer(user_question: str, reference_text: str, markdown: bool = False) -> str:
    focused_reference_text = _extract_focus_reference_text(user_question, reference_text)
    focus_terms = _extract_focus_ngrams(user_question)
    normalized_terms = [normalize_text(term, compact=True) for term in focus_terms if term]

    points: List[Tuple[int, str]] = []
    seen = set()
    for block in (focused_reference_text or reference_text or "").split("\n\n"):
        snippet = re.sub(r"^\(来源:[^)]+\)\s*", "", block).strip()
        if not snippet:
            continue
        cleaned_snippet = re.sub(r"\s+", " ", snippet).strip()
        if len(cleaned_snippet) > 240:
            cleaned_snippet = cleaned_snippet[:240].rstrip() + "..."
        normalized_snippet = normalize_text(cleaned_snippet, compact=True)
        if normalized_snippet in seen:
            continue
        hit_count = sum(1 for term in normalized_terms if term and term in normalized_snippet)
        if normalized_terms and hit_count <= 0:
            continue
        seen.add(normalized_snippet)
        points.append((hit_count, cleaned_snippet))

    points.sort(key=lambda item: (-item[0], len(item[1])))
    top_points = [text for _, text in points[:2]]
    if not top_points:
        return ""

    official_urls = re.findall(r"https?://[^\s)]+", focused_reference_text or reference_text or "")
    check_line = "参考知识没有直接给出更进一步的比较结论，建议按文中提到的官方通知或入口继续核验。"
    if official_urls:
        check_line = f"参考知识没有直接给出更进一步的比较结论，建议优先查阅 {official_urls[0]} 的最新通知。"

    if markdown:
        lines = ["根据现有资料，目前只能确认以下事实：", ""]
        lines.extend(f"- {point}" for point in top_points)
        lines.extend(["", check_line])
        return "\n".join(lines)

    facts = "；".join(top_points)
    return f"根据现有资料，目前只能确认以下事实：{facts}。{check_line}"


def _is_choice_question(user_question: str) -> bool:
    normalized_question = normalize_text(user_question, compact=True)
    if not normalized_question:
        return False
    return any(normalize_text(marker, compact=True) in normalized_question for marker in _CHOICE_QUESTION_MARKERS)


def _extract_focus_reference_text(user_question: str, reference_text: str) -> str:
    focus_terms = [normalize_text(term, compact=True) for term in _extract_focus_ngrams(user_question) if term]
    if not reference_text or not focus_terms:
        return reference_text

    scored_blocks: List[Tuple[int, str]] = []
    for block in reference_text.split("\n\n"):
        snippet = re.sub(r"^\(来源:[^)]+\)\s*", "", block).strip()
        normalized_snippet = normalize_text(snippet, compact=True)
        if not normalized_snippet:
            continue
        hit_count = sum(1 for term in focus_terms if term in normalized_snippet)
        if hit_count > 0:
            scored_blocks.append((hit_count, block))

    if not scored_blocks:
        return reference_text

    max_hit_count = max(hit_count for hit_count, _ in scored_blocks)
    min_hit_count = 1
    if len(focus_terms) >= 3 and max_hit_count >= 3:
        min_hit_count = max_hit_count - 1

    matched_blocks = [block for hit_count, block in scored_blocks if hit_count >= min_hit_count]
    return "\n\n".join(matched_blocks) if matched_blocks else reference_text


def _reference_has_decision_support(user_question: str, reference_text: str) -> bool:
    normalized_reference = normalize_text(_extract_focus_reference_text(user_question, reference_text), compact=True)
    if not normalized_reference:
        return False
    return any(normalize_text(marker, compact=True) in normalized_reference for marker in _DECISION_SUPPORT_MARKERS)


def build_kb_reference(results: List[Dict], limit: int = KB_REFERENCE_LIMIT) -> str:
    parts = []
    for item in results[:limit]:
        snippet = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        if len(snippet) > 360:
            snippet = snippet[:360].rstrip() + "..."
        parts.append(f"(来源:{item['source']} score:{float(item.get('score') or 0.0):.3f}) {snippet}")
    return "\n\n".join(parts)


def retrieve_knowledge_bundle(user_question: str) -> Dict:
    official_site_bundle = retrieve_official_site_bundle(user_question)
    if official_site_bundle.get("results"):
        return official_site_bundle

    kb = index_status()
    faq_match = _find_best_faq_match(user_question)

    try:
        results = query_index(user_question, k=KB_RETRIEVE_CANDIDATE_K)
    except Exception:
        results = []

    selected_results = _select_reference_results(user_question, results, faq_match, limit=KB_REFERENCE_LIMIT)
    if selected_results:
        return {
            "reference_text": build_kb_reference(selected_results, limit=KB_REFERENCE_LIMIT),
            "top_score": float(max(float(item.get("score") or 0.0) for item in selected_results)),
            "results": selected_results,
            "backend": kb.get("backend", "none"),
        }

    if not faq_match:
        return {"reference_text": "", "top_score": 0.0, "results": [], "backend": kb.get("backend", "none")}

    faq_result = _make_faq_reference_result(faq_match)
    if faq_result is None:
        return {"reference_text": "", "top_score": 0.0, "results": [], "backend": kb.get("backend", "none")}

    return {
        "reference_text": build_kb_reference([faq_result], limit=1),
        "top_score": float(faq_result.get("score") or 0.0),
        "results": [faq_result],
        "backend": kb.get("backend", "none"),
    }


def ask_llm(user_question: str, retrieved_answer: str, retrieved_score: float, markdown: bool = False) -> str:
    if not LLM_BASE_URL or not LLM_API_KEY:
        return ""

    if _is_choice_question(user_question) and not _reference_has_decision_support(user_question, retrieved_answer):
        focused_reference_text = _extract_focus_reference_text(user_question, retrieved_answer)
        fallback_answer = _build_grounded_fallback_answer(user_question, focused_reference_text, markdown=markdown)
        if fallback_answer:
            return append_sources_if_missing(fallback_answer, reference_text=focused_reference_text, markdown=markdown)

    sys_prompt = (
        "你是北京理工大学新生助手。\n"
        "严格仅基于提供的参考知识回答；如果参考知识不足，明确说明无法确定并建议用户查证。\n"
        "如果参考知识没有逐字回答用户问题，但足以支持一个稳妥的办理建议、推荐顺序或操作优先级，请明确写成“基于现有资料的建议”，并说明依据；不要因为措辞不是完全一致就直接回答无法确定。\n"
        "建议只允许重组参考知识里已经出现的先后关系、条件关系和操作优先级；不得补充参考知识中没有出现的数字、时长、规则、额外场景或经验性细节。\n"
        "不得引入参考知识未明确写出的新比较维度或判断，例如费用高低、班次密度、是否直达、体验好坏、口味、人气、成功率等；这些内容只有在参考知识明确写出时才能使用。\n"
        "回答要准确、简洁、友好。答案末尾必须列出来源（文件名和相似度分数）。"
    )
    if markdown:
        sys_prompt += "\n输出请使用 Markdown，可用小标题和列表提升可读性。"

    reference_block = f"参考知识：\n{retrieved_answer}" if retrieved_answer else "参考知识：无直接匹配。"

    caution_note = ""
    if retrieved_score and retrieved_score < LLM_MIN_CONFIDENCE:
        caution_note = f"注意：检索到的相似度较低（{retrieved_score:.3f}），请谨慎回答并在无法确定时明确说明。\n"

    raw_answer = call_llm(
        [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": (
                    f"{caution_note}{reference_block}\n\n"
                    f"用户问题：{user_question}\n\n"
                    "请仅基于上述参考知识回答。若证据足以支持建议性结论，请先给出“基于现有资料的建议”，再说明哪些部分是明确事实、哪些部分是基于事实的稳妥推断；建议性结论只能建立在参考知识已经出现的先后关系、条件关系和操作优先级上，禁止补充参考知识中没有出现的操作细节、数字、时长或经验规则，也不要引入参考知识未明确写出的新比较维度，例如费用高低、班次密度、是否直达、体验好坏、口味、人气、成功率等。只有在连建议性结论都无法支持时，才明确回复“无法确定”，并给出可查证入口。"
                    + (
                        "输出为 Markdown；结尾用“### 来源”并以列表列出文件名和 score。"
                        if markdown
                        else "答案末尾用【来源: 文件名 (score)】格式列出。"
                    )
                ),
            },
        ]
    )
    if not raw_answer:
        return ""
    if _find_unbacked_comparison_terms(raw_answer, retrieved_answer):
        fallback_answer = _build_grounded_fallback_answer(user_question, retrieved_answer, markdown=markdown)
        if fallback_answer:
            raw_answer = fallback_answer
    return append_sources_if_missing(raw_answer, reference_text=retrieved_answer, markdown=markdown)


def build_combined_sources_markdown(kb_reference: str, web_sources: List[Dict]) -> str:
    return _build_source_block(reference_text=kb_reference, web_sources=web_sources, markdown=True, label_kb=True)


def ask_llm_with_combined_context(
    user_question: str,
    kb_reference: str,
    kb_score: float,
    web_reference: str,
    web_sources: List[Dict],
    markdown: bool = False,
) -> str:
    if not LLM_BASE_URL or not LLM_API_KEY:
        return ""

    sys_prompt = (
        "你是北京理工大学新生助手。\n"
        "每次回答都必须同时参考两类证据：本地知识库和已抓取到的网页内容。\n"
        "知识库适合稳定流程、校园常识、官方入口；网页内容适合核验最新通知、补充细节和确认当前情况。\n"
        "如果知识库与网页出现冲突，优先采用本次抓取到的官方网页信息，并明确说明冲突点与取舍依据。\n"
        "如果两类证据都不足，请明确说明无法确定，并给出继续核验的官方入口。\n"
        "禁止编造未在知识库或网页中出现的信息。"
    )
    if markdown:
        sys_prompt += "\n输出请使用 Markdown，优先使用以下结构：## 结论、## 核验与补充、## 建议、### 来源。"

    caution_notes = []
    if kb_reference and kb_score < LLM_MIN_CONFIDENCE:
        caution_notes.append(f"知识库最高相似度较低（{kb_score:.3f}），请谨慎引用并明确不确定性。")
    if not web_reference:
        caution_notes.append("本次网页核验未抓到可用正文，只能把知识库作为主依据。")

    raw_answer = call_llm(
        [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": (
                    ("注意事项：\n- " + "\n- ".join(caution_notes) + "\n\n" if caution_notes else "")
                    + f"知识库证据：\n{kb_reference or '无明确命中。'}\n\n"
                    + f"网页核验证据：\n{web_reference or '未抓取到可用网页正文。'}\n\n"
                    + f"用户问题：{user_question}\n\n"
                    + "请综合两类证据作答：先给直接结论，再说明网页核验带来的确认或补充；若网页与知识库不一致，要说明以哪一类为准以及为什么。"
                ),
            },
        ]
    )
    if not raw_answer:
        return ""
    return append_sources_if_missing(
        raw_answer,
        reference_text=kb_reference,
        web_sources=web_sources,
        markdown=markdown,
        label_kb=True,
    )


def build_web_fallback_answer(fetch_results: List[Dict], markdown: bool = False) -> str:
    useful = [item for item in fetch_results if item.get("ok") or item.get("search_only")]
    if not useful:
        return ""

    if markdown:
        lines = ["### 基于抓取网页的摘要"]
        for item in useful[:3]:
            title = str(item.get("title") or item.get("final_url") or item.get("url") or "网页")
            excerpt = re.sub(r"\s+", " ", str(item.get("excerpt") or item.get("search_snippet") or "")).strip()
            prefix = "搜索摘要" if item.get("search_only") and not item.get("ok") else "网页正文"
            lines.append(f"- **{title}**（{prefix}）：{excerpt}")
        sources_markdown = format_web_sources_markdown(useful)
        if sources_markdown:
            lines.append("")
            lines.append(sources_markdown)
        return "\n".join(lines)

    parts = []
    for item in useful[:3]:
        title = str(item.get("title") or item.get("final_url") or item.get("url") or "网页")
        excerpt = re.sub(r"\s+", " ", str(item.get("excerpt") or item.get("search_snippet") or "")).strip()
        parts.append(f"{title}: {excerpt}")
    return "\n".join(parts)


def build_combined_fallback_answer(kb_reference: str, web_sources: List[Dict], markdown: bool = False) -> str:
    if markdown:
        blocks = []
        if kb_reference:
            blocks.append(f"## 知识库检索\n{kb_reference}")
        if web_sources:
            blocks.append(build_web_fallback_answer(web_sources, markdown=True))
        else:
            blocks.append("## 网页核验\n未抓取到可用网页，当前只能基于本地知识库提供参考。")
        sources_block = build_combined_sources_markdown(kb_reference, web_sources)
        if sources_block:
            blocks.append(sources_block)
        return "\n\n".join(blocks) if blocks else "暂时没有匹配到明确答案。"

    parts = []
    if kb_reference:
        parts.append(f"知识库参考：{kb_reference}")
    if web_sources:
        parts.append(build_web_fallback_answer(web_sources, markdown=False))
    else:
        parts.append("网页核验未获取到可用结果。")
    return "\n\n".join(parts) if parts else "暂时没有匹配到明确答案。"


def build_answer(question: str, markdown: bool = False) -> str:
    kb_bundle = retrieve_knowledge_bundle(question)
    retrieved = kb_bundle.get("reference_text") or ""
    top_score = float(kb_bundle.get("top_score") or 0.0)
    kb_results = kb_bundle.get("results") or []
    kb_backend = kb_bundle.get("backend", "none")

    if kb_backend == "official_site_catalog" and kb_results:
        return build_official_site_answer(kb_results, markdown=markdown)

    llm_answer = ask_llm(question, retrieved, top_score, markdown=markdown)
    if llm_answer:
        return llm_answer
    if retrieved:
        if markdown:
            sources_markdown = format_sources_markdown(retrieved)
            source_part = f"\n\n{sources_markdown}" if sources_markdown else ""
            return (
                "### 基于知识库的参考\n"
                f"{retrieved}\n\n"
                "> 如需更准确的实时信息，请以学校和学院最新通知为准。"
                f"{source_part}"
            )
        return f"根据现有资料：{retrieved}\n\n如需更准确的实时信息，请以学校最新通知为准。"
    if markdown:
        return (
            "暂时没有匹配到明确答案。\n\n"
            "你可以尝试：\n"
            "- 换一种问法（例如加上校区、系统名、业务场景）\n"
            "- 使用关键词提问（如 选课、宿舍、校园网、奖助）\n"
            "- 参考学校官网或联系辅导员获取最新通知"
        )
    return "暂时没有匹配到明确答案，建议查看学校官网通知或联系辅导员。"


def build_chat_response(question: str, markdown: bool = False) -> Dict:
    process_steps: List[Dict] = []
    web_sources: List[Dict] = []
    bit_scoped_question = looks_like_bit_query(question)
    kb_bundle = retrieve_knowledge_bundle(question) if bit_scoped_question else {
        "reference_text": "",
        "top_score": 0.0,
        "results": [],
        "backend": "skipped_non_bit_query",
    }
    kb_reference = kb_bundle.get("reference_text") or ""
    top_score = float(kb_bundle.get("top_score") or 0.0)
    kb_results = kb_bundle.get("results") or []
    kb_backend = kb_bundle.get("backend", "none")

    process_steps.append(
        {
            "stage": "kb_retrieve",
            "ok": bool(kb_reference),
            "message": (
                f"官网入口目录匹配成功（results={len(kb_results)}, top_score={top_score:.3f}）"
                if kb_backend == "official_site_catalog" and kb_reference
                else (
                    "问题不属于北理域，已跳过本地知识库，直接进入网页检索"
                    if kb_backend == "skipped_non_bit_query"
                    else (
                    f"本地知识库已完成混合检索（backend={kb_backend}, results={len(kb_results)}, top_score={top_score:.3f}）"
                    if kb_reference
                    else f"本地知识库已完成混合检索（backend={kb_backend}），但未命中明确片段"
                    )
                )
            ),
            "url": "",
        }
    )

    if kb_backend == "official_site_catalog" and kb_results:
        answer = build_official_site_answer(kb_results, markdown=markdown)
        process_steps.append(
            {
                "stage": "answer",
                "ok": True,
                "message": f"已从官网入口目录匹配到 {len(kb_results)} 个候选站点并直接生成回答",
                "url": str(kb_results[0].get("root_url") or ""),
            }
        )
        return {
            "answer": answer,
            "steps": process_steps,
            "web_sources": [],
            "mode": "kb",
            "strategy": "official_site_catalog",
            "kb_score": top_score,
        }

    kb_confident = bool(kb_reference) and top_score >= LLM_MIN_CONFIDENCE
    kb_answer = ask_llm(question, kb_reference, top_score, markdown=markdown) if kb_reference else ""
    kb_answer_needs_web = bool(kb_answer) and _kb_answer_needs_web_followup(kb_answer)
    should_fetch_web = should_fetch_public_web(question, bit_scoped_question=bit_scoped_question, kb_confident=kb_confident)
    if bit_scoped_question and kb_answer_needs_web:
        should_fetch_web = True

    if should_fetch_web:
        try:
            search_bundle = search_and_fetch_public_web(question)
            process_steps.extend(search_bundle.get("steps") or [])
            web_sources = [item for item in (search_bundle.get("results") or []) if item.get("ok") or item.get("search_only")]
        except Exception as exc:
            process_steps.append({"stage": "web_search", "ok": False, "message": f"网页检索失败: {exc}", "url": ""})
            web_sources = []
    else:
        process_steps.append(
            {
                "stage": "web_search",
                "ok": True,
                "message": "当前问题属于校内稳定信息，知识库证据已足够，本轮跳过网页核验以提升响应速度",
                "url": "",
            }
        )

    web_reference = build_web_reference(web_sources) if web_sources else ""
    combined_kb_reference = "" if (kb_answer_needs_web and web_sources) else kb_reference
    combined_kb_score = 0.0 if (kb_answer_needs_web and web_sources) else top_score

    if web_sources:
        answer = ask_llm_with_combined_context(
            question,
            combined_kb_reference,
            combined_kb_score,
            web_reference,
            web_sources,
            markdown=markdown,
        )
        if not answer:
            answer = build_combined_fallback_answer(combined_kb_reference, web_sources, markdown=markdown)
    elif kb_answer:
        answer = kb_answer
    elif kb_confident:
        answer = ask_llm(question, kb_reference, top_score, markdown=markdown)
        if not answer:
            answer = build_combined_fallback_answer(kb_reference, web_sources, markdown=markdown)
    else:
        process_steps.append(
            {
                "stage": "evidence_guard",
                "ok": False,
                "message": f"网页未抓到可用正文，且本地知识库相关性不足（top_score={top_score:.3f}），本轮不输出无依据结论",
                "url": "",
            }
        )
        if markdown:
            answer = (
                "暂时不能可靠回答这个问题。\n\n"
                "本轮没有抓到可用网页正文，而本地知识库与问题的相关性也不足。为了避免编造，我先不给出结论。\n\n"
                "你可以尝试：\n"
                "- 明确写出机构全名、产品名或官方站点名\n"
                "- 把问题缩小到一个可核验点，例如开放时间、步骤、政策条款\n"
                "- 稍后重试，或换成更接近官方标题的问法"
            )
        else:
            answer = "暂时不能可靠回答这个问题：当前没有抓到可用网页正文，本地知识库相关性也不足。为了避免编造，本轮不输出结论。"

    process_steps.append({"stage": "answer", "ok": True, "message": "已完成 RAG 检索、网页核验与汇总回答", "url": ""})
    return {
        "answer": answer,
        "steps": process_steps,
        "web_sources": web_sources,
        "mode": "web" if should_fetch_web else "kb",
        "strategy": "rag_then_web",
        "kb_score": top_score,
    }


def get_ai_runtime_summary() -> Dict:
    provider = "deepseek" if DEEPSEEK_API_KEY else ("openai-compatible" if OPENAI_API_KEY else "faq-only")
    kb = index_status()
    return {
        "provider": provider,
        "llm_enabled": bool(LLM_BASE_URL and LLM_API_KEY),
        "model": LLM_MODEL,
        "base_url": LLM_BASE_URL,
        "kb_index_ready": kb.get("ready", False),
        "kb_backend": kb.get("backend", "none"),
        "kb_doc_count": kb.get("doc_count", 0),
        "kb_error": kb.get("error", ""),
    }