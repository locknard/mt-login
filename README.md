# mt-login（馒头保号）

用 Docker + Playwright 定期自动登录网站（支持 TOTP 2FA），用于“保号”。

## 快速开始

### Web UI（推荐）

1) 准备 `.env`（参考 `.env.example`），至少填写：
- `APP_MASTER_KEY`
- `APP_BASIC_AUTH_USER` / `APP_BASIC_AUTH_PASSWORD`

```bash
mkdir -p data
# 生产/长期运行：直接用 GHCR 镜像（推荐）
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d

# 本地开发：从当前仓库构建
# docker compose up -d --build
```

2) 打开 `http://localhost:53100/accounts`（可用 `APP_PORT` 改端口），用 BasicAuth 登录后：
- 新建账号：填写 `login_url` / `target_url` / 用户名密码 / TOTP secret / selectors
- 查看历史：Runs 页面查看最近 50 次执行记录和截图

针对 `kp.m-team.cc`：可以直接打开 `http://localhost:53100/accounts/new?preset=kp` 预填已探测到的登录页 selectors（`#username` / `#password` / `button[type="submit"]`）和默认 `target_url`。
OTP 输入框如果不确定，可以留空（服务会在登录后自动尝试探测）。
如果你是从 Google Authenticator 导出账号，可以在创建账号时粘贴 `otpauth-migration://...`，服务会自动解析并保存 secret（不会保存 migration URL 本身）。

### 单次 CLI（保留）

仍支持跑一次（主要用于调试 selectors / 2FA 流程）。注意：这是单账号模式；多账号请用 Web UI。

```bash
docker build -t mt-login .
mkdir -p data
cp .env.cli.example .env.cli
docker run --rm --env-file .env.cli \
  -e BOT_STATE_PATH=/data/state.json \
  -e BOT_SCREENSHOT_PATH=/data/screenshot.png \
  -e BOT_ERROR_SCREENSHOT_PATH=/data/error.png \
  -v "$(pwd)/data:/data" \
  mt-login python main.py
```

## 配置说明

Web UI 相关见 `.env.example` 的 `APP_*`；账号/selector 在 Web 页面里维护。

### 如何获取 TOTP Secret

有两种方式可以在 Web UI 中配置 TOTP：

**方式一：直接输入 TOTP Secret**

1. 在目标网站的 2FA 设置页面，选择"手动输入密钥"或"无法扫描二维码？"
2. 复制显示的 Base32 字符串（例如：`JBSWY3DPEHPK3PXP`）
3. 在创建账号时粘贴到 "TOTP secret" 字段

**方式二：使用 Google Authenticator 导出（推荐）**

如果你已经在 Google Authenticator 中添加了该网站的 2FA：

1. 打开 Google Authenticator App
2. 点击右上角 ⋮（三个点）→ "转移账号" → "导出账号"
3. 选择要导出的账号（可多选）
4. App 会显示一个二维码
5. 使用微信/其他扫码工具扫描该二维码
6. 得到的链接格式为 `otpauth-migration://offline?data=...`
7. 在创建账号时粘贴到 "TOTP migration URL" 字段，系统会自动解析并提取 secret

> 注意：migration URL 不会被保存，系统只会提取其中的 TOTP secret 并加密存储。

## Docker 镜像（GHCR）

仓库会在 `main` 分支更新时自动发布 `latest`：
- `ghcr.io/locknard/mt-login:latest`

拉取并运行（示例）：

```bash
docker pull ghcr.io/locknard/mt-login:latest
mkdir -p data
docker run --rm -p 53100:8000 --env-file .env -v "$PWD/data:/data" ghcr.io/locknard/mt-login:latest
```

如果你在 Apple Silicon（arm64）上遇到 `no matching manifest`，可临时用 `docker pull --platform=linux/amd64 ...`（或在 compose 里加 `platform: linux/amd64`）。

Docker Compose（更推荐，含 `restart` / `shm_size` 等常用配置）：

```bash
mkdir -p data
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
curl -fsS http://localhost:53100/healthz
```

## 安全提示

- `TOTP secret` / 密码会写入 SQLite，但使用 `APP_MASTER_KEY` 进行了加密；务必妥善保管 `APP_MASTER_KEY`。
- 建议为该账号开启最小权限、并关注网站风控/封号策略。
