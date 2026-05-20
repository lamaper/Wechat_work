import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from modules.ai.service import build_chat_response, retrieve_official_site_bundle


def assert_top_site(query: str, expected_url: str) -> None:
    bundle = retrieve_official_site_bundle(query)
    assert bundle.get("backend") == "official_site_catalog", f"unexpected backend for {query}: {bundle}"
    results = bundle.get("results") or []
    assert results, f"no site match for {query}"
    top_url = str(results[0].get("root_url") or "")
    assert top_url == expected_url, f"top url mismatch for {query}: {top_url} != {expected_url}"

    payload = build_chat_response(query, markdown=True)
    assert payload.get("strategy") == "official_site_catalog", f"unexpected strategy for {query}: {payload}"
    answer = str(payload.get("answer") or "")
    assert expected_url in answer, f"answer missing expected url for {query}: {answer}"


def main() -> None:
    cases = [
        ("奖学金应该看哪个网站？", "https://student.bit.edu.cn/"),
        ("校园网和正版软件去哪个官网？", "https://itc.bit.edu.cn/"),
        ("国际学生招生看哪个网址？", "https://isc.bit.edu.cn/"),
        ("密码忘了去哪个入口？", "https://sso.bit.edu.cn/"),
    ]

    for query, expected_url in cases:
        print(f"check: {query}")
        assert_top_site(query, expected_url)

    generic_payload = build_chat_response("学校哪个网址能够查询相关信息？", markdown=True)
    assert generic_payload.get("strategy") == "official_site_catalog"
    generic_answer = str(generic_payload.get("answer") or "")
    assert "https://www.bit.edu.cn/" in generic_answer
    assert "https://ehall.bit.edu.cn/" in generic_answer
    print("official site smoke test passed")


if __name__ == "__main__":
    main()