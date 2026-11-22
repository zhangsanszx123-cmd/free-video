# 腾讯云 1Panel 自动部署

推送到 main 后，GitHub Actions 依次运行部署脚本测试、后端测试（CI 临时 MySQL 8.4）和多阶段 Docker 构建，在 Runner 导出压缩镜像并通过 SSH 直接传给服务器；服务器校验压缩包 SHA-256 和镜像配置 digest，导入、启动并通过健康检查后才记录成功版本。流程与 ai-tools 相同，镜像不经过任何镜像仓库。

## 当前部署参数

| 项目 | 配置 |
|---|---|
| GitHub 仓库 | zhangsanszx123-cmd/free-video |
| 服务器 / 部署用户 | 43.143.85.207 / ubuntu |
| 项目目录 | /opt/projects/free-video |
| 访问地址 | http://43.143.85.207（80 端口；ai-tools 在 8081） |
| 应用上游 | http://127.0.0.1:13001（容器内 8000） |
| MySQL | 1Panel 的 MySQL 8.4，1panel-network 内主机名 `mysql:3306`，不对公网开放 |
| 数据库 / 账号 | `freevideo` / `freevideo`（专用账号，不使用 root） |
| 持久目录 | storage/transcriptions（转录记录）、storage/downloads（30 分钟临时文件） |
| 应用镜像 | ghcr.io/zhangsanszx123-cmd/free-video:sha256-配置digest（仅作本地标签，不推送） |

应用只发布 `127.0.0.1:13001:8000`，安全组无需开放 13001 或 8000。容器限制 1 GB 内存，只运行一个 uvicorn 进程：任务队列、验证码和游客限额锁都在内存里，不能扩成多进程。

## 反向代理与真实访客 IP

游客额度、登录和注册限流按来源 IP 计算，代码不会信任任意请求里的 `X-Forwarded-For`。容器通过 `uvicorn --proxy-headers` 加环境变量 `FORWARDED_ALLOW_IPS` 只信任 1panel-network 的网关地址（初始化时自动写入，当前为 172.18.0.1），OpenResty 转发的 `X-Forwarded-For` 才会被采用。1Panel 反向代理必须由代理覆盖该头，而不是追加：

```nginx
location ^~ / {
    proxy_pass http://127.0.0.1:13001;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $http_connection;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 300s;
    client_max_body_size 200m;
}
```

`proxy_buffering off` 保证 AI 流式输出和下载进度实时返回；下载大文件需要较长超时。部署后用带伪造头的请求验证：直接连应用端口发送的伪造 `X-Forwarded-For` 不应改变记录的来源地址。

## 一次性准备

1. 服务器目录（需要 sudo）：

```bash
sudo install -d -o ubuntu -g ubuntu -m 750 /opt/projects/free-video
sudo install -d -o 1000 -g 1000 -m 750 /opt/projects/free-video/storage/transcriptions /opt/projects/free-video/storage/downloads
```

2. 在 1Panel 安装 MySQL 8.4（不勾选端口外部访问），创建数据库 `freevideo`（utf8mb4）和同名专用账号。
3. 本机运行初始化（密码隐藏输入，不写入命令行或本地文件）：

```powershell
node deploy/setup-production.mjs --origin http://43.143.85.207
```

仅检查参数、不连接服务器：加 `--dry-run`。脚本自动完成：

- 从 MySQL 容器取出 CA 公有证书并验证其能校验服务器证书。
- 用同一镜像的 mysql 客户端经 1panel-network 和 TLS（VERIFY_CA）实际登录一次，确认账号、密码和库名。
- 生成 `deploy/runtime.env`（权限 600）：随机 SESSION_SECRET、数据库账号、`PUBLIC_BASE_URL`、`ALLOWED_ORIGINS`、可信代理地址；本地 `backend/.env` 中非空的 `DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY` 一并带上（只显示键名）。
- 安装 Compose 与部署脚本，不启动应用、不改数据库。

已有成功部署记录时脚本自动跳过；已有配置与本次目标不同时保留原文件并停止。

4. 在 1Panel 创建反向代理网站：域名 `43.143.85.207`，端口 80，代理地址 `127.0.0.1:13001`，再把上面的代理源文合并进去。
5. GitHub：Settings → Environments → 新建 `production`，限制部署分支为 main；Environment secrets 填 SSH_HOST、SSH_PORT、SSH_USER、SSH_PRIVATE_KEY、SSH_KNOWN_HOSTS（与 ai-tools 相同的值，不是 Variables）。

## 首次发布与验证

```bash
git push origin main
```

成功后在服务器执行：

```bash
cd /opt/projects/free-video
export APP_IMAGE=$(cat deploy/current-image)
docker compose ps
curl -f http://127.0.0.1:13001/api/health
```

浏览器访问 `http://43.143.85.207`。应用启动时自动创建缺失的数据表和默认套餐，不需要手工导入 SQL。管理员账号不会自动创建，在容器中用隐藏输入初始化：

```bash
docker compose exec app python -m app.admin_auth bootstrap --username admin
```

## HTTP IP 模式的限制

- 当前只有 HTTP 和 IP，会话和密码不加密；配置 HTTPS 前不要通过公网输入真实账号、管理员密码或支付信息。
- `SESSION_SECURE=false`；邮件验证（要求 HTTPS 的 `PUBLIC_BASE_URL`）和 ZPAY 支付保持关闭，对应变量初始化时不写入。
- 海外平台（YouTube 等）暂不支持：`YTDLP_PROXY` 留空。抖音、B 站不受影响。

切到域名和 HTTPS 后，编辑服务器 `deploy/runtime.env`：`SESSION_SECURE=true`、`PUBLIC_BASE_URL` 和 `ALLOWED_ORIGINS` 改成 HTTPS 地址；再按需补充 SMTP、`AUTH_EMAIL_VERIFICATION_REQUIRED=true`、`ZPAY_PID`/`ZPAY_KEY`，然后重建应用：

```bash
APP_IMAGE=$(cat deploy/current-image) docker compose up -d --no-build --pull never --force-recreate --wait --wait-timeout 180 app
```

## 失败保护与回滚

服务器先接收并校验压缩包，导入后对已加载镜像重新计算 config digest 并核对，再更新应用，最多等待 180 秒就绪；失败时自动恢复上一成功镜像，Actions 仍报告失败。首次部署没有上一版本，失败时停止新应用。手工回滚：

```bash
cd /opt/projects/free-video
bash deploy/deploy.sh --local "$(cat deploy/previous-image)"
```

回滚只恢复应用镜像，不恢复数据库或上传文件。镜像用配置 digest 命名：服务器 Docker 29 使用 containerd 镜像存储，`docker image inspect` 的 ID 是 manifest digest，与配置 digest 不同，服务器把核实后的本地 ID 记录在 `deploy/releases/image-ids/`。

## 备份

定期备份 MySQL（1Panel 的数据库备份）、storage/transcriptions、runtime.env、deploy/secrets 和 deploy/releases/history.log。环境文件备份应加密并限制访问。
