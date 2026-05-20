# BIT 新生助手 — 项目架构框架图

## 1. 项目目录结构（物理视图）

```
Wechat_work/
└── app/
    ├── backend/                          ← Flask 后端服务
    │   ├── app.py                        ← Flask 入口
    │   ├── .env / .env.example           ← 环境配置
    │   ├── requirements*.txt             ← Python 依赖
    │   ├── auth_identities.json          ← 特权用户白名单
    │   ├── official_url_allowlist.json   ← 校园站点目录
    │   ├── feature3.db                   ← SQLite 数据库 (运行时)
    │   ├── kb_*.*                        ← 知识库索引 (运行时)
    │   ├── modules/
    │   │   ├── shared/                   ← 共享基础设施
    │   │   │   ├── db.py                 ← SQLite 数据访问层
    │   │   │   ├── paths.py              ← 路径常量
    │   │   │   ├── text_utils.py         ← 文本处理工具
    │   │   │   └── id_utils.py           ← ID 生成
    │   │   ├── auth/                     ← 认证模块
    │   │   │   ├── service.py            ← BIT 登录、会话、权限
    │   │   │   └── routes.py             ← 认证 API 路由
    │   │   ├── ai/                       ← AI 问答模块
    │   │   │   ├── service.py            ← 问答核心逻辑 (~870 行)
    │   │   │   ├── routes.py             ← 聊天 API 路由
    │   │   │   ├── kb.py                 ← 知识库索引与检索
    │   │   │   └── web_fetcher.py        ← 网页搜索与抓取
    │   │   ├── feature3/                 ← 工单 + 微信模块
    │   │   │   ├── service.py            ← 工单逻辑、微信回调
    │   │   │   ├── routes.py             ← 工单 API + /wechat
    │   │   │   └── wechat_utils.py       ← 微信 API 客户端
    │   │   ├── pages/                    ← 静态页面路由
    │   │   │   └── routes.py
    │   │   └── diagnostics/              ← 健康诊断
    │   │       └── routes.py
    │   └── tests/                        ← 烟雾测试
    │
    ├── data/                             ← 知识库源文件 (Markdown)
    │   ├── faq.md                        ← FAQ (Q:/A: 格式)
    │   └── *.md                          ← 知识库文档
    │
    └── web/                              ← 前端静态文件
        ├── theme.css                     ← 全局设计系统 (~1780 行)
        ├── common.js                     ← 公共工具函数
        ├── login.html                    ← BIT 统一认证登录页
        ├── index.html                    ← 首页 (功能入口)
        ├── chat.html                     ← AI 智能问答页
        ├── place.html                    ← 校园地点搜索页
        ├── freshman.html                 ← 新生提问 & 追踪页
        └── senior.html                   ← 学长回答面板
```

> **关键关系**: `backend/`、`data/`、`web/` 是 `app/` 下的三个**并列目录**。
> - `backend/` 启动时读取 `../data/` 下的 Markdown 文件构建知识库索引
> - `backend/` 通过 `static_folder="../web"` 将前端文件作为静态资源分发
> - `data/` 和 `web/` 都不依赖 `backend/`，它们是独立的数据/展示层

---

## 2. 系统全景架构（逻辑视图）

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            用户入口                                       │
│                                                                          │
│   浏览器 (新生)      浏览器 (学长)      浏览器 (访客)      微信公众平台    │
└────────┬──────────────────┬──────────────────┬──────────────────┬────────┘
         │                  │                  │                  │
         └──────────────────┴────────┬─────────┘                  │
                                     │                            │
                              HTTP   │                     HTTP   │
                                     ▼                            │
┌─────────────────────────────────────────────────────────────────▼────────┐
│                         app/backend/ (Flask 应用层)                       │
│                                                                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌───────────────────┐  │
│  │ Auth Guard │  │  Session   │  │  CORS      │  │  Static File      │  │
│  │(before_req)│  │(8h,HTTPOnly│  │  Error     │  │  Serving          │  │
│  │ 权限校验    │  │ Samesite)  │  │  Handling  │  │  (→ ../web/)      │  │
│  └────────────┘  └────────────┘  └────────────┘  └───────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      modules/ (业务模块)                          │   │
│  │                                                                  │   │
│  │  ┌──────────┐  ┌──────────────┐  ┌──────────────┐               │   │
│  │  │  auth/   │  │     ai/      │  │  feature3/   │               │   │
│  │  │ BIT认证  │  │  AI智能问答  │  │ 工单+微信    │               │   │
│  │  └────┬─────┘  └──────┬───────┘  └──────┬───────┘               │   │
│  │       │               │                 │                        │   │
│  │       └───────────────┼─────────────────┘                        │   │
│  │                       ▼                                          │   │
│  │              ┌────────────────┐                                  │   │
│  │              │   shared/      │  ← 共享基础设施                   │   │
│  │              │ db, paths,     │                                  │   │
│  │              │ text_utils,    │                                  │   │
│  │              │ id_utils       │                                  │   │
│  │              └────────────────┘                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  数据读写:                         静态文件引用:                          │
│  ┌──────────────────┐              ┌──────────────────┐                  │
│  │ ../data/*.md     │              │ ../web/*.html     │                  │
│  │ (知识库源文件)    │              │ ../web/*.css      │                  │
│  │                  │              │ ../web/*.js       │                  │
│  └──────────────────┘              └──────────────────┘                  │
│  feature3.db / kb_*.*  (本地运行时产物)                                  │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
         │
         │ HTTPS / API 调用
         ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          外部服务                                        │
│                                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │ BIT SSO  │  │DeepSeek  │  │DuckDuckGo│  │So360/    │  │WeChat API │ │
│  │统一认证   │  │LLM API   │  │ 网页搜索  │  │Baidu搜索  │  │ 客服消息   │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └───────────┘ │
└──────────────────────────────────────────────────────────────────────────┘


app/ 下的三个并列目录:

  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │  backend/   │    │   data/     │    │   web/      │
  │             │    │             │    │             │
  │ Flask 后端  │───►│ 知识库源文件 │    │ 前端静态页面 │◄─── Flask 分发
  │ 服务端逻辑  │ 读 │ .md 文档    │    │ HTML/CSS/JS │    (static_folder)
  │             │ 取 │             │    │             │
  │ 产物:       │    └─────────────┘    └─────────────┘
  │ feature3.db │
  │ kb_*.faiss  │    并列关系: backend/ ≡ data/ ≡ web/
  └─────────────┘    不存在谁包含谁
```

---

## 3. 模块职责矩阵

| 模块 | 位置 | 职责 | 路由 | 权限 |
|---|---|---|---|---|
| `modules/auth/` | `backend/` | BIT 统一身份认证、会话管理、权限控制 | `/login`, `/api/auth/*` | 公开 |
| `modules/ai/` | `backend/` | AI 问答、知识库检索、网页搜索、LLM 合成 | `/api/chat`, `/api/kb_query`, `/api/rebuild_index` | `PERM_USE_APP` |
| `modules/feature3/` | `backend/` | 工单系统、微信回调、自动回答队列 | `/api/questions/*`, `/api/answers`, `/api/tasks/*`, `/wechat` | 混合 |
| `modules/pages/` | `backend/` | 将 `../web/` 下的静态文件分发到对应路由 | `/`, `/chat`, `/place`, `/freshman`, `/senior` | `PERM_USE_APP` |
| `modules/diagnostics/` | `backend/` | 运行时健康诊断 | `/api/demo_status` | `PERM_USE_APP` |
| `modules/shared/` | `backend/` | 数据库、路径、文本工具、ID 生成 | — | 内部模块 |

---

## 4. 核心数据流

### 4.1 AI 问答流程

```
用户提问
    │
    ▼
POST /api/chat
    │
    ├── ① 官方站点目录匹配 (official_url_allowlist.json)
    │   └── 命中 → 直接返回站点推荐
    │
    ├── ② 高频缓存查询 (选课/网络/宿舍/校园卡等)
    │   └── 命中 → 直接返回缓存答案
    │
    ├── ③ 知识库混合检索
    │   ├── 读取 ../data/*.md 构建索引
    │   ├── 向量检索 (FAISS IndexFlatIP)
    │   ├── 词汇检索 (bigram overlap, 权重 0.38)
    │   └── 混合加权合并 (向量 0.62 + 词汇 0.38)
    │
    ├── ④ [可选] 公网搜索
    │   ├── DuckDuckGo + So360 + Baidu 并行搜索
    │   ├── 域名加权: .bit.edu.cn > .edu.cn > 其他
    │   ├── robots.txt 检查 → HTML 抓取 → 正文提取
    │   └── 生成网页参考摘要
    │
    ├── ⑤ LLM 合成 (DeepSeek / OpenAI)
    │   └── 输入: 系统提示词 + KB 证据 + Web 证据 + 用户问题
    │
    └── ⑥ 返回 { answer, steps[], web_sources[], mode, kb_score }
```

### 4.2 认证流程

```
用户访问任意页面
    │
    ▼
before_request (Auth Guard)
    │
    ├── 路径公开? (/login, /wechat, /api/auth/*, 静态资源) → 放行
    │
    └── 路径受保护
        ├── 无 session → Web: 302 /login  |  API: 401
        └── 有 session → 检查权限掩码
            ├── OK → 放行
            └── 不足 → Web: 302  |  API: 403

POST /api/auth/login
    ├── bit_login 包 → BIT SSO (sso.bit.edu.cn)
    └── 构建 session user (身份哈希 + 权限掩码)
```

### 4.3 工单流程

```
┌─ 学生提问 ───────────────────────────────────────────────┐
│                                                          │
│  Web:  POST /api/questions  →  创建 question → id+code   │
│  微信: POST /wechat (XML)    →  创建 question → 自动回复  │
│                                                          │
│  [可选] AI 自动回答入队 → Worker 线程 → build_answer()    │
│                                                          │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌─ 学长回答 ───────────────────────────────────────────────┐
│                                                          │
│  /senior → 待回答列表 → 输入答案 → POST /api/answers      │
│  [可选] 微信客服消息推送通知提问者                         │
│                                                          │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌─ 学生追踪 ───────────────────────────────────────────────┐
│                                                          │
│  /freshman (我的问题) 或 微信 "查询 <id> <code>" → 查看   │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 5. 数据库 ER 图

```
┌──────────────┐       ┌──────────────────────┐       ┌──────────────┐
│    users     │       │      questions        │       │   answers    │
├──────────────┤       ├──────────────────────┤       ├──────────────┤
│ id (PK)      │──┐    │ id (PK)              │    ┌──│ id (PK)      │
│ identity     │  │    │ from_user_id (FK)    │◄───┘  │ question_id  │──┐
│ role         │  └───►│ title                 │       │ answerer_id  │  │
│ source       │       │ content               │       │ answer_type  │  │
│ nickname     │       │ status                │       │ content      │  │
│ created_at   │       │ view_code             │       │ created_at   │  │
└──────────────┘       │ channel               │       │ updated_at   │  │
                       │ client_id             │       └──────────────┘  │
                       │ created_at            │                         │
                       │ updated_at            │◄────────────────────────┘
                       └───────────────────────┘       (question_id UNIQUE)

┌──────────────────┐       ┌──────────────────────────┐
│  auth_identities │       │         tasks             │
├──────────────────┤       ├──────────────────────────┤
│ student_code(PK) │       │ id (PK)                  │
│ display_name     │       │ type                     │
│ permissions (INT)│       │ payload (JSON)           │
│ enabled          │       │ status                   │
│ note            │       │ attempts / max_attempts   │
│ created_at      │       │ last_error               │
│ updated_at      │       │ created_at / updated_at   │
└──────────────────┘       └──────────────────────────┘
```

---

## 6. 前端页面与路由映射

```
app/web/                          路由              权限
  ├── login.html        →       /login             公开
  ├── index.html        →       /                  PERM_USE_APP
  ├── chat.html         →       /chat              PERM_USE_APP
  ├── place.html        →       /place             PERM_USE_APP
  ├── freshman.html     →       /freshman          PERM_USE_APP
  └── senior.html       →       /senior            PERM_ANSWER

前端技术: 原生 HTML/CSS/JS，无框架。腾讯地图 JavaScript API GL。
```

---

## 7. 技术栈

| 层级 | 技术 | 所属目录 |
|---|---|---|
| 后端框架 | Flask 3.0.3 | `backend/` |
| 数据库 | SQLite (WAL 模式) | `backend/feature3.db` (运行时) |
| AI/LLM | DeepSeek API / OpenAI 兼容 | — (外部) |
| 向量检索 | FAISS + TF-IDF + TruncatedSVD | `backend/kb_*.*` (运行时) |
| 嵌入模型 | all-MiniLM-L6-v2 | — (外部) |
| 网页抓取 | BeautifulSoup4 + requests | `backend/` |
| 认证 | bit-login (BIT SSO) | `backend/` |
| 前端 | 原生 HTML/CSS/JS | `web/` |
| 知识库 | Markdown 文档 | `data/` |
| 地图 | 腾讯地图 JavaScript API GL | — (外部) |
| 微信 | 微信公众平台消息+客服 | — (外部) |
| 生产部署 | Gunicorn (可选) | `backend/` |

---

## 8. 模块间依赖关系

```
                         ┌──────────┐
                         │  app.py  │  (Flask 入口 + 编排)
                         └────┬─────┘
          ┌─────────┬─────────┼─────────┬──────────┐
          ▼         ▼         ▼         ▼          ▼
        auth/      ai/    feature3/  pages/   diagnostics/
          │         │         │         │          │
          └─────────┴─────────┴─────────┘          │
                      │                            │
                      ▼                            │
              ┌──────────────┐                     │
              │   shared/    │◄────────────────────┘
              └──────────────┘

特殊依赖: feature3/service.py → ai/service.py (build_answer 用于自动 AI 回答)
所有模块 → shared/db.py (数据库访问)
所有模块 → shared/paths.py (路径解析)
ai/kb.py  → shared/text_utils.py (词汇检索评分)
ai/kb.py  → ../data/*.md (知识库源文件读取)
pages/    → ../web/*.html (静态文件分发)
```

| 调用方 | 被调用方 | 用途 |
|---|---|---|
| `feature3/service.py` | `ai/service.py` | 工单自动 AI 回答 |
| `ai/kb.py` | `../data/*.md` | 读取知识库源文件 |
| `pages/routes.py` | `../web/*.html` | 分发前端页面 |
| 所有模块 | `shared/db.py` | 数据库访问 |
| 所有模块 | `shared/paths.py` | 文件路径解析 |
| `ai/kb.py` | `shared/text_utils.py` | 词汇检索评分 |
| `feature3/service.py` | `shared/id_utils.py` | 生成 view_code |
