# VPS 部署指南（Nginx + HTTPS + Docker Compose）

目标：一台便宜 VPS（2C4G 起，镜像体积 ~3GB、embedding 模型驻留内存 ~500MB）
+ 一个域名，跑出可以写进简历的在线 demo。

## 0. 前置

- VPS：Ubuntu 22.04+，放行 80/443（云厂商安全组 + `ufw allow 80,443/tcp`）
- 域名 A 记录指向 VPS 公网 IP
- 本机或 VPS 上有 Node 18+（构建前端）

## 1. 装 Docker（VPS 上）

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

## 2. 拉代码 + 配环境

```bash
git clone <你的仓库地址> && cd anti-fraud-agent

cat > .env <<'EOF'
DEEPSEEK_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
OPENAI_API_KEY=sk-...
POSTGRES_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET=$(openssl rand -hex 32)
EOF
# 注意：heredoc 不展开 $()，上面两行请手动执行 openssl 后粘贴真实值
```

## 3. 构建前端

```bash
cd frontend && npm ci && npm run build && cd ..   # 产出 frontend/dist
```

（前端 API 调用全部是相对路径 `/api`，WS 自动按 https→wss，无需配置后端地址）

## 4-5. 签证书（bootstrap 配置，无需手工改 nginx）

证书还不存在时 443 server 块会让 nginx 起不来，所以先用 HTTP-only 的
bootstrap 配置起服务、签出证书，再切正式配置：

```bash
export DOMAIN=demo.example.com   # 换成你的域名

# 4a. 用 bootstrap 配置生成 live 配置（compose 挂载的是 nginx.live.conf）
sed "s/YOUR_DOMAIN/$DOMAIN/g" deploy/nginx.bootstrap.conf > deploy/nginx.live.conf
docker compose -f deploy/docker-compose.prod.yml up -d nginx
curl http://$DOMAIN/            # 应返回 bootstrap ok

# 4b. 签证书（webroot 模式）
docker run --rm \
  -v anti-fraud-agent-prod_letsencrypt:/etc/letsencrypt \
  -v anti-fraud-agent-prod_certbot-webroot:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d $DOMAIN --email you@example.com --agree-tos --no-eff-email

# 4c. 切到正式配置（含 443/TLS/反代）
sed "s/YOUR_DOMAIN/$DOMAIN/g" deploy/nginx.conf > deploy/nginx.live.conf
```

## 6. 全栈起服务

```bash
docker compose -f deploy/docker-compose.prod.yml up -d --build
# 国内网络慢：build args 打开 HF_ENDPOINT / PIP_INDEX 镜像（见 compose 注释）
docker compose -f deploy/docker-compose.prod.yml ps     # app 应为 healthy
curl -s https://$DOMAIN/api/healthz                     # {"status":"ok"}
```

打开 `https://demo.example.com`，注册账号，贴一条可疑短信看流式推理。

## 7. 证书续期（cron）

```bash
crontab -e
# 每周一 3:00 续期并热加载 nginx
0 3 * * 1 docker run --rm -v anti-fraud-agent-prod_letsencrypt:/etc/letsencrypt -v anti-fraud-agent-prod_certbot-webroot:/var/www/certbot certbot/certbot renew --webroot -w /var/www/certbot && docker compose -f /home/$USER/anti-fraud-agent/deploy/docker-compose.prod.yml exec nginx nginx -s reload
```

## 8. 运维速查

```bash
docker compose -f deploy/docker-compose.prod.yml logs -f app    # 应用日志
docker compose -f deploy/docker-compose.prod.yml exec db psql -U app antifraud   # 进库
docker compose -f deploy/docker-compose.prod.yml exec redis redis-cli            # 进 redis
docker compose -f deploy/docker-compose.prod.yml up -d --build app               # 只更新后端
```

## 已知事项 / 后续

- **表结构演进**：当前用 ORM `create_all`（只建不改）。加列/改表请引入 Alembic
  迁移（`alembic init` + autogenerate），这是下一个该补的工程项
- **限流真实 IP**：nginx 已传 `X-Forwarded-For`，限流器优先读它
- **多 worker**：待处理会话已在 Redis，可加 `UVICORN_WORKERS=2`（注意每 worker
  常驻 ~500MB embedding 模型内存）
- **演示账号**：首次启动自动建 admin/admin123，对外演示前请改密或删除
  （`backend/db/database.py` 的 `_seed_default_user`）
