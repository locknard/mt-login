# mt-2fa

用 Docker + Playwright 定期自动登录网站（支持 TOTP 2FA），用于“保号”。

## 快速开始

### Web UI（推荐）

1) 准备 `.env`（参考 `.env.example`），至少填写：
- `APP_MASTER_KEY`
- `APP_BASIC_AUTH_USER` / `APP_BASIC_AUTH_PASSWORD`

```bash
mkdir -p data
docker compose up -d --build
```

2) 打开 `http://localhost:53100/accounts`（可用 `APP_PORT` 改端口），用 BasicAuth 登录后：
- 新建账号：填写 `login_url` / `target_url` / 用户名密码 / TOTP secret / selectors
- 查看历史：Runs 页面查看最近 50 次执行记录和截图

针对 `kp.m-team.cc`：可以直接打开 `http://localhost:53100/accounts/new?preset=kp` 预填已探测到的登录页 selectors（`#username` / `#password` / `button[type="submit"]`）和默认 `target_url`。
OTP 输入框如果不确定，可以留空（服务会在登录后自动尝试探测）。
如果你是从 Google Authenticator 导出账号，可以在创建账号时粘贴 `otpauth-migration://...`，服务会自动解析并保存 secret（不会保存 migration URL 本身）。

### 单次 CLI（保留）

仍支持用环境变量跑一次（适合调试 selectors）：

```bash
docker build -t mt-2fa .
mkdir -p data
docker run --rm --env-file .env \
  -e BOT_STATE_PATH=/data/state.json \
  -e BOT_SCREENSHOT_PATH=/data/screenshot.png \
  -e BOT_ERROR_SCREENSHOT_PATH=/data/error.png \
  -v "$(pwd)/data:/data" \
  mt-2fa python main.py
```

## 配置说明

Web UI 相关见 `.env.example` 的 `APP_*`；账号/selector 在 Web 页面里维护。

## 发布到 GitHub 时建议提交/忽略

- 建议提交：`mt2fa/`、`templates/`、`static/`、`Dockerfile`、`docker-compose.yml`、`requirements.txt`、`.env.example`、`README.md`、`.dockerignore`、`.gitignore`
- 不要提交：`.env`、`data/`（包含 `app.db`、cookie state、截图、运行历史）、`local/`（你自己的临时文件/截图/zip）

## 安全提示

- `TOTP secret` / 密码会写入 SQLite，但使用 `APP_MASTER_KEY` 进行了加密；务必妥善保管 `APP_MASTER_KEY`。
- 建议为该账号开启最小权限、并关注网站风控/封号策略。
