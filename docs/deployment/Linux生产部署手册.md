# Linux 生产部署手册

## 1. 适用环境

- Ubuntu 24.04（或同级 Debian 系）
- systemd 可用
- Nginx 可用

## 2. 部署步骤

1. 拉取代码到服务器
2. 创建 Python 环境并安装依赖
3. 配置 `app/backend/.env`
4. 本机先跑通 `gunicorn`
5. 配置并启动 systemd
6. 配置 Nginx 反向代理
7. 配置 HTTPS
8. 做上线验收

## 3. 关键检查

- Gunicorn 进程稳定
- Nginx upstream 可达
- `/login`、`/chat`、`/freshman` 可访问
- `/wechat` 可通过微信后台校验

## 4. 建议

上线前先跑一遍：

- 工单冒烟测试
- AI 网页检索冒烟测试

这样能提前发现外部依赖问题。
