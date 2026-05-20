import hashlib
import json
import os
import pickle
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from modules.shared.paths import BACKEND_ROOT, DATA_ROOT
from modules.shared.text_utils import lexical_score, normalize_text

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

try:
    import faiss
except Exception:
    faiss = None

try:
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
except Exception:
    TruncatedSVD = None
    TfidfVectorizer = None

# Files stored alongside backend
BASE_DIR = BACKEND_ROOT
INDEX_PATH = BASE_DIR / "kb_index.faiss"
META_PATH = BASE_DIR / "kb_meta.json"
TEXTS_PATH = BASE_DIR / "kb_texts.json"
STATE_PATH = BASE_DIR / "kb_state.json"
VECTORIZER_PATH = BASE_DIR / "kb_vectorizer.pkl"
SVD_PATH = BASE_DIR / "kb_vector_svd.pkl"

# Small model for embeddings; change as needed
EMB_MODEL_NAME = os.getenv("KB_EMB_MODEL_NAME", "all-MiniLM-L6-v2")
EMB_DEVICE = (os.getenv("KB_EMB_DEVICE", "cpu") or "cpu").strip()
CHUNK_SIZE = max(240, int(os.getenv("KB_CHUNK_SIZE", "560")))
CHUNK_OVERLAP = max(40, min(CHUNK_SIZE // 2, int(os.getenv("KB_CHUNK_OVERLAP", "140"))))
LEXICAL_MIN_SCORE = max(0.0, float(os.getenv("KB_LEXICAL_MIN_SCORE", "0.05")))
VECTOR_QUERY_K = max(8, int(os.getenv("KB_VECTOR_QUERY_K", "18")))
LEXICAL_QUERY_K = max(8, int(os.getenv("KB_LEXICAL_QUERY_K", "18")))
HYBRID_VECTOR_WEIGHT = max(0.0, float(os.getenv("KB_HYBRID_VECTOR_WEIGHT", "0.62")))
HYBRID_LEXICAL_WEIGHT = max(0.0, float(os.getenv("KB_HYBRID_LEXICAL_WEIGHT", "0.38")))
VECTOR_MAX_FEATURES = max(4000, int(os.getenv("KB_VECTOR_MAX_FEATURES", "30000")))
VECTOR_DIM = max(32, int(os.getenv("KB_VECTOR_DIM", "256")))

QUERY_EXPANSIONS = {
    "选课": ["教务", "培养方案", "补退选", "教学日历"],
    "课程": ["教务", "培养方案", "补退选", "教学日历"],
    "转专业": ["学籍", "教务", "接收计划", "遴选办法"],
    "转系": ["转专业", "学籍", "接收计划", "遴选办法"],
    "宿舍": ["住宿", "入住", "宿管", "辅导员"],
    "校园网": ["网络", "认证", "账号", "信息化"],
    "网络": ["校园网", "认证", "账号", "信息化"],
    "图书馆": ["借阅", "馆藏", "数据库", "座位预约"],
    "奖学金": ["资助", "奖助", "申请", "评审"],
    "助学金": ["资助", "奖助", "申请", "评审"],
    "报到": ["迎新", "入学", "材料", "流程"],
    "军训": ["国防教育", "训练", "安排"],
    "医保": ["医疗", "健康", "报销", "门诊", "校医院"],
    "报销": ["医保", "校医院", "票据", "转诊"],
    "车辆": ["入校", "车证", "通行", "停车"],
    "家长车": ["车辆", "入校", "迎新", "停车"],
    "心理": ["咨询", "健康", "适应", "情绪"],
    "就业": ["职业", "招聘", "实习", "简历"],
    "出国": ["留学", "交换", "国际", "语言"],
    "交换": ["出国", "留学", "国际", "访学"],
    "校园卡": ["充值", "挂失", "补办", "支付"],
    "考试": ["补考", "缓考", "作弊", "成绩"],
    "挂科": ["补考", "重修", "成绩", "学业预警"],
    "作弊": ["考试", "处分", "学术诚信", "违规"],
    "体测": ["体育", "体质", "健康", "测试"],
    "软件": ["正版", "信息化", "VPN", "校园网"],
    "VPN": ["校园网", "校外访问", "数据库", "信息化"],
    "大创": ["创新", "创业", "科研", "竞赛"],
    "竞赛": ["大创", "挑战杯", "数学建模", "ACM"],
    "科研": ["大创", "实验室", "导师", "论文"],
    "志愿": ["服务", "公益", "时长", "实践"],
    "实践": ["社会", "志愿", "暑期", "调研"],
    "实习": ["就业", "招聘", "简历", "面试"],
    "保研": ["推免", "研究生", "GPA", "综测"],
    "考研": ["研究生", "复习", "初试", "复试"],
    "社团": ["活动", "纳新", "学生组织", "成长"],
    "毕业": ["学分", "论文", "答辩", "学位"],
}


def _split_with_overlap(text: str, chunk_size: int, overlap: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    step = max(1, chunk_size - overlap)
    chunks = []
    for start in range(0, len(text), step):
        part = text[start : start + chunk_size].strip()
        if len(part) < 24:
            continue
        chunks.append(part)
        if start + chunk_size >= len(text):
            break
    return chunks


def _iter_markdown_blocks(raw: str) -> List[str]:
    blocks: List[str] = []
    heading_stack: List[str] = []
    paragraph: List[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        title = " / ".join(heading_stack[-2:]).strip()
        body = " ".join(paragraph).strip()
        paragraph.clear()
        if not body:
            return
        if title:
            blocks.append(f"{title}\n{body}")
        else:
            blocks.append(body)

    for line in (raw or "").replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(title)
            continue

        paragraph.append(stripped)

    flush_paragraph()
    return blocks


def _expand_query(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return ""

    expanded_terms: List[str] = [query]
    normalized = normalize_text(query)
    for key, aliases in QUERY_EXPANSIONS.items():
        if key in query or key in normalized:
            expanded_terms.extend(aliases)

    dedup = []
    seen = set()
    for term in expanded_terms:
        token = term.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        dedup.append(token)
    return " ".join(dedup)


def _load_texts_from_data(data_dir: Path) -> List[Dict]:
    texts = []

    def append_chunks(source_name: str, chunk_id: int, content: str) -> int:
        for chunk in _split_with_overlap(content, CHUNK_SIZE, CHUNK_OVERLAP):
            texts.append({"source": source_name, "chunk_id": chunk_id, "text": chunk})
            chunk_id += 1
        return chunk_id

    for p in sorted((data_dir).glob("*.md")):
        raw = p.read_text(encoding="utf-8")
        blocks = _iter_markdown_blocks(raw)
        chunk_id = 0
        for block in blocks:
            chunk_id = append_chunks(p.name, chunk_id, block)

        # Empty markdown files or parsing failures should still degrade gracefully.
        if not blocks:
            chunk_id = append_chunks(p.name, chunk_id, raw)
    return texts


def _compute_data_signature(data_dir: Path) -> str:
    digest = hashlib.sha1()
    for path in sorted(data_dir.glob("*.md")):
        stat = path.stat()
        digest.update(path.name.encode("utf-8"))
        digest.update(str(stat.st_size).encode("utf-8"))
        digest.update(str(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))).encode("utf-8"))
    return digest.hexdigest()


def _save_meta_and_texts(texts: List[Dict]):
    metas = [{"source": t["source"], "chunk_id": t["chunk_id"]} for t in texts]
    text_values = [t["text"] for t in texts]
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(metas, f, ensure_ascii=False)
    with open(TEXTS_PATH, "w", encoding="utf-8") as f:
        json.dump(text_values, f, ensure_ascii=False)


def _save_state(state: Dict):
    merged = {
        "ready": bool(state.get("ready")),
        "backend": state.get("backend", "none"),
        "doc_count": int(state.get("doc_count", 0)),
        "updated_at": int(time.time()),
        "error": state.get("error", ""),
        "warning": state.get("warning", ""),
        "data_signature": state.get("data_signature", ""),
        "vector_backend": state.get("vector_backend", ""),
    }
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)


def _load_state() -> Dict:
    if not STATE_PATH.exists():
        return {"ready": False, "backend": "none", "doc_count": 0, "error": ""}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "ready": bool(data.get("ready")),
            "backend": data.get("backend", "none"),
            "doc_count": int(data.get("doc_count", 0)),
            "updated_at": int(data.get("updated_at", 0)),
            "error": data.get("error", ""),
            "warning": data.get("warning", ""),
            "data_signature": data.get("data_signature", ""),
            "vector_backend": data.get("vector_backend", ""),
        }
    except Exception:
        return {
            "ready": False,
            "backend": "none",
            "doc_count": 0,
            "error": "state_parse_error",
            "warning": "",
            "data_signature": "",
            "vector_backend": "",
        }


_BUILD_LOCK = threading.Lock()


def _ensure_index_current(data_dir: Optional[Path] = None, index_path: Optional[Path] = None) -> Dict:
    data_dir = data_dir or DATA_ROOT
    index_path = index_path or INDEX_PATH
    current_signature = _compute_data_signature(data_dir)
    state = _load_state()
    texts_ready = META_PATH.exists() and TEXTS_PATH.exists()
    if texts_ready and state.get("data_signature") == current_signature:
        return state
    return build_index(data_dir=data_dir, index_path=index_path)


def _cleanup_vector_artifacts(index_path: Path) -> None:
    for path in (index_path, VECTORIZER_PATH, SVD_PATH):
        if path.exists():
            path.unlink()


def _to_dense_array(matrix):
    toarray = getattr(matrix, "toarray", None)
    if callable(toarray):
        return toarray()
    return matrix


def _as_float32_matrix(matrix) -> np.ndarray:
    return np.asarray(_to_dense_array(matrix), dtype=np.float32)


def _normalize_vectors(vectors) -> None:
    normalize_l2 = getattr(faiss, "normalize_L2", None)
    if normalize_l2 is None:
        raise RuntimeError("faiss normalize_L2 unavailable")
    normalize_l2(vectors)


def _new_faiss_index(dim: int):
    index_cls = getattr(faiss, "IndexFlatIP", None)
    if index_cls is None:
        raise RuntimeError("faiss IndexFlatIP unavailable")
    return index_cls(dim)


def build_index(data_dir: Optional[Path] = None, index_path: Optional[Path] = None):
    data_dir = data_dir or DATA_ROOT
    index_path = index_path or INDEX_PATH

    with _BUILD_LOCK:
        texts = _load_texts_from_data(data_dir)
        if not texts:
            raise RuntimeError("no documents found to index")

        _save_meta_and_texts(texts)
        data_signature = _compute_data_signature(data_dir)
        legacy_force = os.getenv("KB_FORCE_LEXICAL", "").strip().lower() in {"1", "true", "yes", "on"}
        warning = "legacy KB_FORCE_LEXICAL detected; hybrid retrieval is now preferred" if legacy_force else ""

        if TfidfVectorizer is None or faiss is None:
            state = {
                "ready": True,
                "backend": "lexical",
                "doc_count": len(texts),
                "error": "tfidf/faiss unavailable, fallback to lexical index",
                "warning": warning,
                "data_signature": data_signature,
                "vector_backend": "",
            }
            _save_state(state)
            _cleanup_vector_artifacts(index_path)
            return state

        try:
            sentences = [t["text"] for t in texts]
            vectorizer = TfidfVectorizer(
                analyzer="char",
                ngram_range=(2, 4),
                lowercase=False,
                sublinear_tf=True,
                max_features=VECTOR_MAX_FEATURES,
            )
            matrix = vectorizer.fit_transform(sentences)

            svd = None
            dense_vectors = matrix
            if TruncatedSVD is not None:
                max_components = min(VECTOR_DIM, max(1, matrix.shape[0] - 1), max(1, matrix.shape[1] - 1))
                if max_components >= 32:
                    svd = TruncatedSVD(n_components=max_components, random_state=42)
                    dense_vectors = svd.fit_transform(matrix)
                else:
                    dense_vectors = _as_float32_matrix(matrix)
            else:
                dense_vectors = _as_float32_matrix(matrix)

            dense_vectors = _as_float32_matrix(dense_vectors)
            if len(dense_vectors.shape) != 2 or int(dense_vectors.shape[1]) <= 0:
                raise RuntimeError("invalid vector dimension")

            _normalize_vectors(dense_vectors)
            dim = int(dense_vectors.shape[1])
            index = _new_faiss_index(dim)
            add_vectors = getattr(index, "add", None)
            if add_vectors is None:
                raise RuntimeError("faiss index add unavailable")
            add_vectors(dense_vectors)

            with open(VECTORIZER_PATH, "wb") as f:
                pickle.dump(vectorizer, f, protocol=pickle.HIGHEST_PROTOCOL)
            with open(SVD_PATH, "wb") as f:
                pickle.dump(svd, f, protocol=pickle.HIGHEST_PROTOCOL)
            faiss.write_index(index, str(index_path))
            state = {
                "ready": True,
                "backend": "hybrid",
                "doc_count": len(texts),
                "error": "",
                "warning": warning,
                "data_signature": data_signature,
                "vector_backend": "char_tfidf_svd" if svd is not None else "char_tfidf",
            }
            _save_state(state)
            return state
        except Exception as exc:
            _cleanup_vector_artifacts(index_path)
            state = {
                "ready": True,
                "backend": "lexical",
                "doc_count": len(texts),
                "error": f"vector_build_failed: {str(exc)[:240]}",
                "warning": warning,
                "data_signature": data_signature,
                "vector_backend": "",
            }
            _save_state(state)
            return state


def load_index(index_path: Optional[Path] = None):
    index_path = index_path or INDEX_PATH
    if not META_PATH.exists() or not TEXTS_PATH.exists():
        return None

    with open(META_PATH, "r", encoding="utf-8") as f:
        metas = json.load(f)
    with open(TEXTS_PATH, "r", encoding="utf-8") as f:
        texts = json.load(f)

    if index_path.exists() and faiss is not None and VECTORIZER_PATH.exists():
        try:
            index = faiss.read_index(str(index_path))
            with open(VECTORIZER_PATH, "rb") as f:
                vectorizer = pickle.load(f)
            svd = None
            if SVD_PATH.exists():
                with open(SVD_PATH, "rb") as f:
                    svd = pickle.load(f)
            state = _load_state()
            return {
                "backend": "hybrid",
                "index": index,
                "metas": metas,
                "texts": texts,
                "vectorizer": vectorizer,
                "svd": svd,
                "vector_backend": state.get("vector_backend", "char_tfidf"),
            }
        except Exception:
            pass

    return {"backend": "lexical", "index": None, "metas": metas, "texts": texts}


_MODEL = None
_MODEL_LOCK = threading.Lock()


def _resolve_local_model_path() -> Optional[str]:
    model_cache_name = EMB_MODEL_NAME.replace("/", "--")
    candidate_roots = []
    hf_home = os.getenv("HF_HOME", "").strip()
    hub_cache = os.getenv("HUGGINGFACE_HUB_CACHE", "").strip()

    if hub_cache:
        candidate_roots.append(Path(hub_cache))
    if hf_home:
        candidate_roots.append(Path(hf_home) / "hub")
    candidate_roots.append(Path.home() / ".cache" / "huggingface" / "hub")

    for root in candidate_roots:
        model_root = root / f"models--sentence-transformers--{model_cache_name}"
        snapshots_dir = model_root / "snapshots"
        if not snapshots_dir.exists():
            continue
        snapshots = sorted((path for path in snapshots_dir.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True)
        if snapshots:
            return str(snapshots[0])
    return None


def _get_model():
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                if SentenceTransformer is None:
                    raise RuntimeError("sentence-transformers unavailable")
                model_name_or_path = _resolve_local_model_path() or EMB_MODEL_NAME
                model_kwargs = {}
                if EMB_DEVICE and EMB_DEVICE.lower() != "auto":
                    model_kwargs["device"] = EMB_DEVICE
                _MODEL = SentenceTransformer(model_name_or_path, **model_kwargs)
    return _MODEL


def index_status() -> Dict:
    loaded = load_index()
    state = _load_state()
    if not loaded:
        return {
            "ready": False,
            "backend": "none",
            "doc_count": 0,
            "error": state.get("error", ""),
        }
    return {
        "ready": True,
        "backend": loaded["backend"],
        "doc_count": len(loaded["texts"]),
        "error": state.get("error", ""),
    }


def _query_lexical(query: str, metas: List[Dict], texts: List[str], k: int) -> List[Dict]:
    expanded_query = _expand_query(query)
    scored = []
    for idx, text in enumerate(texts):
        score = lexical_score(expanded_query, text)
        source = str((metas[idx] if idx < len(metas) else {}).get("source") or "")
        if source and source.replace("_", "") in expanded_query:
            score = min(1.0, score + 0.05)
        scored.append((score, idx))
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, idx in scored:
        if len(results) >= k:
            break
        if score < LEXICAL_MIN_SCORE and results:
            break
        meta = metas[idx] if idx < len(metas) else {}
        results.append(
            {
                "score": float(score),
                "source": meta.get("source") or "unknown.md",
                "chunk_id": int(meta.get("chunk_id", 0)),
                "text": texts[idx],
            }
        )

    # Ensure at least one candidate is returned for downstream fallback synthesis.
    if not results and scored:
        score, idx = scored[0]
        meta = metas[idx] if idx < len(metas) else {}
        results.append(
            {
                "score": float(score),
                "source": meta.get("source") or "unknown.md",
                "chunk_id": int(meta.get("chunk_id", 0)),
                "text": texts[idx],
            }
        )
    return results


def _query_vector(query: str, loaded: Dict, k: int) -> List[Dict]:
    if not loaded.get("index") or loaded.get("vectorizer") is None:
        return []

    expanded_query = _expand_query(query) or query
    query_matrix = loaded["vectorizer"].transform([expanded_query])
    if loaded.get("svd") is not None:
        q_emb = loaded["svd"].transform(query_matrix)
    else:
        q_emb = _as_float32_matrix(query_matrix)
    q_emb = _as_float32_matrix(q_emb)
    if len(q_emb.shape) != 2 or int(q_emb.shape[1]) <= 0:
        return []
    _normalize_vectors(q_emb)
    distances, indices = loaded["index"].search(q_emb, k)

    results = []
    metas = loaded["metas"]
    texts = loaded["texts"]
    for score, idx in zip(distances[0], indices[0]):
        if idx < 0:
            continue
        meta = metas[idx] if idx < len(metas) else {}
        normalized_score = max(0.0, min(1.0, (float(score) + 1.0) / 2.0))
        results.append(
            {
                "score": float(normalized_score),
                "raw_vector_score": float(score),
                "source": meta.get("source") or "unknown.md",
                "chunk_id": int(meta.get("chunk_id", 0)),
                "text": texts[idx],
            }
        )
    return results


def _merge_hybrid_results(lexical_results: List[Dict], vector_results: List[Dict], k: int) -> List[Dict]:
    merged: Dict[Tuple[str, int], Dict] = {}

    def ensure_entry(item: Dict) -> Dict:
        key = (str(item.get("source") or "unknown.md"), int(item.get("chunk_id", 0)))
        entry = merged.get(key)
        if entry is None:
            entry = {
                "source": key[0],
                "chunk_id": key[1],
                "text": item.get("text") or "",
                "score": 0.0,
                "lexical_score": 0.0,
                "vector_score": 0.0,
                "raw_vector_score": 0.0,
            }
            merged[key] = entry
        elif not entry.get("text") and item.get("text"):
            entry["text"] = item.get("text") or ""
        return entry

    for rank, item in enumerate(vector_results, start=1):
        entry = ensure_entry(item)
        entry["vector_score"] = max(float(entry.get("vector_score") or 0.0), float(item.get("score") or 0.0))
        entry["raw_vector_score"] = max(float(entry.get("raw_vector_score") or 0.0), float(item.get("raw_vector_score") or 0.0))
        entry["vector_rank"] = min(int(entry.get("vector_rank") or 10**9), rank)

    for rank, item in enumerate(lexical_results, start=1):
        entry = ensure_entry(item)
        entry["lexical_score"] = max(float(entry.get("lexical_score") or 0.0), float(item.get("score") or 0.0))
        entry["lexical_rank"] = min(int(entry.get("lexical_rank") or 10**9), rank)

    for entry in merged.values():
        weighted_score = 0.0
        active_weight = 0.0
        if float(entry.get("vector_score") or 0.0) > 0:
            weighted_score += HYBRID_VECTOR_WEIGHT * float(entry.get("vector_score") or 0.0)
            active_weight += HYBRID_VECTOR_WEIGHT
        if float(entry.get("lexical_score") or 0.0) > 0:
            weighted_score += HYBRID_LEXICAL_WEIGHT * float(entry.get("lexical_score") or 0.0)
            active_weight += HYBRID_LEXICAL_WEIGHT
        if active_weight <= 0:
            active_weight = max(HYBRID_VECTOR_WEIGHT + HYBRID_LEXICAL_WEIGHT, 1.0)

        score = weighted_score / active_weight
        if float(entry.get("vector_score") or 0.0) > 0 and float(entry.get("lexical_score") or 0.0) > 0:
            score = min(1.0, score + 0.06)
        entry["score"] = float(score)

    ordered = sorted(
        merged.values(),
        key=lambda item: (
            float(item.get("score") or 0.0),
            float(item.get("vector_score") or 0.0),
            float(item.get("lexical_score") or 0.0),
        ),
        reverse=True,
    )
    return ordered[:k]


def query_index(query: str, k: int = 3, index_path: Optional[Path] = None):
    _ensure_index_current(index_path=index_path)
    loaded = load_index(index_path=index_path)
    if not loaded:
        # In query path, avoid hidden writes and fall back to in-memory lexical retrieval.
        texts = _load_texts_from_data(DATA_ROOT)
        if not texts:
            return []
        metas = [{"source": t["source"], "chunk_id": t["chunk_id"]} for t in texts]
        values = [t["text"] for t in texts]
        return _query_lexical(query, metas, values, k)

    backend = loaded["backend"]
    metas = loaded["metas"]
    texts = loaded["texts"]

    lexical_results = _query_lexical(query, metas, texts, max(k, LEXICAL_QUERY_K))
    if backend != "hybrid":
        return lexical_results[:k]

    try:
        vector_results = _query_vector(query, loaded, max(k, VECTOR_QUERY_K))
        hybrid_results = _merge_hybrid_results(lexical_results, vector_results, max(k, VECTOR_QUERY_K))
        if hybrid_results:
            return hybrid_results[:k]
    except Exception as exc:
        state = _load_state()
        if not state.get("error"):
            _save_state({**state, "error": f"vector_query_failed: {str(exc)[:240]}"})

    return lexical_results[:k]
