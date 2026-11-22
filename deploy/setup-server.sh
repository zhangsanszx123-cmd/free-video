#!/usr/bin/env bash
# Invoked by setup-production.mjs over SSH stdin; credentials never appear in argv.
set -Eeuo pipefail
umask 077
mkdir -p /opt/projects/free-video 2>/dev/null || true
cd /opt/projects/free-video
test -w . || { echo '项目目录不可写，请先创建 /opt/projects/free-video 并归部署账户所有。' >&2; exit 1; }
mkdir -p deploy/secrets deploy/releases
chmod 700 deploy deploy/secrets deploy/releases
exec 9>deploy/.deploy.lock
flock -n 9 || { echo '已有部署正在进行，请稍后重试。' >&2; exit 1; }
if [[ -s deploy/current-image ]]; then
  echo '已有成功部署，保留现有生产配置；无需重复初始化。'
  exit 20
fi
docker info >/dev/null
docker network inspect 1panel-network >/dev/null
command -v openssl >/dev/null
command -v ss >/dev/null
if [[ -n "$(ss -ltnH 'sport = :13001')" ]]; then
  echo '本机 13001 端口已被占用，尚未安装配置。' >&2
  exit 1
fi
mkdir -p storage/transcriptions storage/downloads
for directory in storage/transcriptions storage/downloads; do
  chown 1000:1000 "$directory" 2>/dev/null || true
  if [[ "$(stat -c %u "$directory")" != 1000 ]]; then
    echo "目录 $directory 需要归容器 UID 1000 所有，请执行：sudo chown 1000:1000 /opt/projects/free-video/$directory" >&2
    exit 1
  fi
done
stage=$(mktemp -d "$PWD/deploy/.setup.XXXXXX")
cleanup() {
  rm -f -- "$stage/runtime.env" "$stage/mysql-ca.pem" "$stage/server.crt" "$stage/docker-compose.yml" "$stage/deploy.sh"
  rmdir -- "$stage"
}
trap cleanup EXIT
printf '%s' "$RUNTIME_B64" | base64 -d > "$stage/runtime.env"
printf '%s' "$COMPOSE_B64" | base64 -d > "$stage/docker-compose.yml"
printf '%s' "$DEPLOY_B64" | base64 -d > "$stage/deploy.sh"
database=$(docker ps --format '{{.Names}}' | grep -E '^1Panel-mysql-' | head -n 1 || true)
[[ -n "$database" ]] || { echo '未找到运行中的 1Panel MySQL 容器。' >&2; exit 1; }
docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "$database" | grep -qw 1panel-network || { echo 'MySQL 不在 1panel-network 网络中。' >&2; exit 1; }
docker exec "$database" cat /var/lib/mysql/ca.pem > "$stage/mysql-ca.pem"
docker exec "$database" cat /var/lib/mysql/server-cert.pem > "$stage/server.crt"
openssl verify -CAfile "$stage/mysql-ca.pem" "$stage/server.crt" >/dev/null || { echo 'MySQL CA 无法校验服务器证书。' >&2; exit 1; }
if [[ -s deploy/secrets/mysql-ca.pem ]]; then
  old_ca=$(openssl x509 -in deploy/secrets/mysql-ca.pem -noout -fingerprint -sha256)
  new_ca=$(openssl x509 -in "$stage/mysql-ca.pem" -noout -fingerprint -sha256)
  [[ "$old_ca" == "$new_ca" ]] || { echo '已有 CA 与当前 MySQL 的 CA 不同，保留原文件并停止。' >&2; exit 1; }
fi
mysql_image=$(docker inspect -f '{{.Config.Image}}' "$database")
chmod 644 "$stage/mysql-ca.pem"
# Real client over the same network path as the app: verifies the account, database and TLS chain.
if ! printf '%s' "$PASSWORD_B64" | base64 -d | docker run --rm -i --network 1panel-network -v "$stage/mysql-ca.pem:/ca/mysql-ca.pem:ro" "$mysql_image" \
  sh -c 'MYSQL_PWD=$(cat) exec mysql -h mysql -u"$1" --ssl-mode=VERIFY_CA --ssl-ca=/ca/mysql-ca.pem "$2" -Nse "SELECT 1"' sh "$MYSQL_USER_NAME" "$MYSQL_DB_NAME" >/dev/null 2>&1; then
  echo "无法用专用账号 $MYSQL_USER_NAME 通过 TLS 连接数据库 $MYSQL_DB_NAME，请检查账号、密码、库名和授权。" >&2
  exit 1
fi
echo 'MySQL 专用账号、数据库和 TLS 证书链校验通过。'
gateway=$(docker network inspect 1panel-network -f '{{(index .IPAM.Config 0).Gateway}}')
[[ "$gateway" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo '无法确定 1panel-network 网关，无法配置可信代理地址。' >&2; exit 1; }
printf 'FORWARDED_ALLOW_IPS=%s\n' "$gateway" >> "$stage/runtime.env"
if [[ -s deploy/runtime.env ]]; then
  for key in MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE PUBLIC_BASE_URL FORWARDED_ALLOW_IPS; do
    old_value=$(grep -m1 "^${key}=" deploy/runtime.env || true)
    new_value=$(grep -m1 "^${key}=" "$stage/runtime.env" || true)
    [[ -n "$old_value" && "$old_value" == "$new_value" ]] || { echo '已有运行配置与本次目标不同，保留原文件并停止。' >&2; exit 1; }
  done
  echo '保留已有运行配置和会话密钥。'
else
  chmod 600 "$stage/runtime.env"
  mv -- "$stage/runtime.env" deploy/runtime.env
fi
chmod 600 deploy/runtime.env
if [[ ! -s deploy/secrets/mysql-ca.pem ]]; then mv -- "$stage/mysql-ca.pem" deploy/secrets/mysql-ca.pem; fi
chmod 644 deploy/secrets/mysql-ca.pem
APP_IMAGE=ghcr.io/zhangsanszx123-cmd/free-video:setup-check docker compose --project-directory "$PWD" -f "$stage/docker-compose.yml" config --quiet
if [[ -f docker-compose.yml ]]; then cp -- docker-compose.yml "deploy/releases/compose-before-setup-$(date -u +%Y%m%dT%H%M%SZ).yml"; fi
mv -- "$stage/docker-compose.yml" docker-compose.yml
mv -- "$stage/deploy.sh" deploy/deploy.sh
chmod 600 docker-compose.yml deploy/deploy.sh
echo '服务器目录、CA、运行变量和 Compose 已准备完成。未启动应用，未修改数据库。'
