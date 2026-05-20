
RAG 工作流程
整个查询流程在 service.py:1159 的 build_chat_response() 中编排，分为以下阶段：

阶段 1：判断问题范围
looks_like_bit_query() 判断问题是否与北理工相关。

阶段 2：本地知识库检索（RAG）
retrieve_knowledge_bundle() 执行：

官网目录匹配 — 如果用户问"网址/入口/官网"，直接从 official_url_allowlist.json 匹配推荐站点，命中则直接返回，跳过后续所有步骤。
FAQ 匹配 — 遍历 faq.md 中所有 Q/A 对，逐条计算 lexical_score()。
混合检索 — 调用 query_index()：
向量检索：将 query 转为 TF-IDF char-ngram 向量 → SVD 降维 → FAISS IndexFlatIP 做余弦相似度搜索
词汇检索：遍历所有 chunk 计算 character bigram 重叠分（O(n) 复杂度）
混合合并：向量分 × 0.62 + 词汇分 × 0.38，去重排序
结果精选 — _select_reference_results() 做 focus-term 加权、来源去重、每来源上限 2 条。
阶段 3：第一次 LLM 调用（仅 KB 证据）
ask_llm() 将 KB 检索结果 + 用户问题发给 DeepSeek，生成第一版回答。

阶段 4：决定是否需要网页抓取
should_fetch_public_web() 在以下情况触发：

非北理工问题（总是触发）
KB 置信度低（score < 0.60）
问题含"时效信号词"（最新、通知、公告、开放时间…）
KB 回答含不确定标记（无法确定、建议查阅…）
阶段 5：网页搜索 + 抓取（爬虫）
search_and_fetch_public_web() 执行：

并行搜索 3 个搜索引擎（DuckDuckGo + So360 + Baidu），用 ThreadPoolExecutor
评分排序：按域名权威度（.bit.edu.cn > .edu.cn > .gov.cn > 其他）+ query token 匹配
逐个抓取 top N 个候选 URL（默认 3 个）—— 这是串行的
每个 URL：检查 robots.txt（HTTP 请求）→ GET 页面 → BeautifulSoup 提取正文
阶段 6：第二次 LLM 调用（KB + Web 证据）
ask_llm_with_combined_context() 将 KB + 网页证据一起发给 LLM，生成最终回答。系统 prompt 要求 LLM 优先采用网页信息。

阶段 7：事实核查（可能触发第三次 LLM 调用）
_revise_answer_against_reference() 检查回答中是否有参考材料未提及的断言（如"免费""更便捷"），如有则再次调用 LLM 修正。

速度慢的可能原因
瓶颈 1：两次串行 LLM 调用（最严重）
service.py:1215 和 service.py:1244 各调用一次 LLM：


KB检索 → LLM调用#1(生成KB版回答) → 判断需网页 → 网页搜索+抓取 → LLM调用#2(综合KB+Web)
第一次 LLM 调用的结果在触发网页抓取后被丢弃了。当 KB 置信度不够高或答案含不确定标记时，第一次 LLM 调用完全浪费，白白消耗 5-15 秒。这在大多数触发网页的场景下都会发生。

瓶颈 2：网页抓取是串行的
web_fetcher.py:863 中候选 URL 是逐个抓取的：


for item in candidates:
    fetched = fetch_public_web_url(url, ...)  # 串行！
每个 URL 的抓取链路：

robots.txt 检查（HTTP GET，超时 2s）
页面 HTTP GET（超时 8s）
BeautifulSoup HTML 解析
抓取 3 个 URL 最坏情况需要 ~30 秒（3 × (2s + 8s)）。

瓶颈 3：第一次 LLM 调用超时设为 15 秒
service.py:61 OPENAI_TIMEOUT = 15，这是单次调用上限。如果 DeepSeek API 响应慢，每次调用都会接近这个时间。两次调用加起来就是 30 秒。

瓶颈 4：词汇检索是 O(n) 全量遍历
kb.py:494-533 的 _query_lexical() 对所有 chunk 逐一计算 lexical_score()。虽然当前 22 个文档的 chunk 数量不算巨大，但这是纯 CPU 计算，没有索引加速。

瓶颈 5：每次请求都从磁盘加载索引
kb.py:634-635 每次查询调用 _ensure_index_current() → load_index()，从磁盘读取 FAISS 索引文件 + vectorizer pickle + SVD pickle。这些文件虽然不大，但增加了固定的 I/O 延迟。

瓶颈 6：事实核查可能触发第三次 LLM 调用
service.py:805 的 _revise_answer_against_reference() 在发现未经验证的断言时，会再次调用 LLM 修正。这是三次 LLM 调用中最坏情况。

瓶颈 7：3 个搜索引擎的等待
虽然 DuckDuckGo + So360 + Baidu 是并行的，但 as_completed 模式下要等最慢的那个返回。默认超时 8 秒，如果某个引擎响应慢，会拖慢整个搜索阶段。

总结：延迟构成估算（最坏情况，触发网页抓取的场景）
阶段	估计耗时
KB 检索（词汇+向量+合并）	0.2-1s
第一次 LLM 调用	5-15s
3 搜索引擎并行查询	2-8s
串行抓取 3 个网页	6-30s
第二次 LLM 调用	5-15s
事实核查（可能触发第三次）	0-15s
总计	18-84s
最核心的问题是两次串行 LLM 调用 + 串行网页抓取。如果你想优化，优先级最高的是：(1) 先判断是否需要网页，再决定是否调用 LLM，避免浪费第一次调用；(2) 将网页抓取改为并行；(3) 考虑对非时效性问题缓存 LLM 回答。