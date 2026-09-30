#!/bin/sh
# 늘봄 서버 설치 — EC2 인스턴스 안, 저장소 루트에서:  sudo sh deploy/install.sh
#
# 여러 번 돌려도 안전하다. 파일을 제자리에 놓고 서비스를 켤 뿐이다.
#
# ── 처음 서버를 세울 때 전체 순서 ──────────────────────────────────────
#
#   접속          CloudShell에서 aws ssm start-session --target <인스턴스ID>
#                 (프롬프트가 sh-5.2$ 로 바뀌면 인스턴스 안이다)
#
#   도구          sudo dnf install -y git python3.11 python3.11-pip postgresql16
#
#   코드          git clone https://github.com/poro832/Nulbom.git ~/Nulbom
#                 cd ~/Nulbom && python3.11 -m venv .venv
#                 .venv/bin/pip install -e .
#
#   앱 설정       cp .env.example .env && chmod 600 .env && nano .env
#                 PUBLIC_BASE_URL=https://nuelbom.duckdns.org
#                 STREAM_BASE_URL=wss://nuelbom.duckdns.org
#                 RECORDINGS_BUCKET=sgu-pj-03-nulbom-recordings
#
#   DuckDNS       sudo nano /etc/duckdns.env   (deploy/duckdns.env.example 참고)
#                 sudo chmod 600 /etc/duckdns.env
#
#   이 스크립트   sudo sh deploy/install.sh
#
#   보안그룹      80(인증서 발급), 443(전화망) 인바운드. 22는 닫아 둔다.
#
# ── 지켜야 할 것 ──────────────────────────────────────────────────────
#
#   터미널에서는 영문 입력 모드. 한글 모드로 치면 첫 글자가 사라지거나
#   안 보이는 바이트가 섞인다(2026-09-30: sudo→udo, nuelbom→n?nuelbom).
#
#   .env 를 셸로 읽지 않는다(. ./.env 금지). 옛 값이 셸에 남아 파일을 고쳐도
#   옛 값으로 돈다. 앱은 app.serve 가 python-dotenv로 읽는다.
#
#   테스트용 초기화(reset_for_tests, 명부 테스트)는 원격 DB에서 거부된다.
#   RDS를 대상으로 pytest를 돌리지 않는다.
set -eu

here=$(cd "$(dirname "$0")" && pwd)

if [ "$(id -u)" -ne 0 ]; then
	echo "sudo로 돌려야 한다: sudo sh deploy/install.sh" >&2
	exit 1
fi

# Caddy 바이너리. 공식 배포처에서 받는다.
if [ ! -x /usr/local/bin/caddy ]; then
	curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=amd64" -o /tmp/caddy
	install -m 0755 /tmp/caddy /usr/local/bin/caddy
	rm -f /tmp/caddy
fi

id caddy >/dev/null 2>&1 || \
	useradd --system --home-dir /var/lib/caddy --create-home --shell /usr/sbin/nologin caddy

install -m 0755 "$here/duckdns-update" /usr/local/bin/duckdns-update
install -d /etc/caddy
install -m 0644 "$here/Caddyfile" /etc/caddy/Caddyfile
install -m 0644 \
	"$here/systemd/nulbom.service" \
	"$here/systemd/caddy.service" \
	"$here/systemd/duckdns.service" \
	"$here/systemd/duckdns.timer" \
	/etc/systemd/system/

/usr/local/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

systemctl daemon-reload
systemctl enable --now nulbom.service caddy.service

if [ -f /etc/duckdns.env ]; then
	systemctl enable --now duckdns.timer
else
	# 없으면 타이머가 5분마다 실패만 쌓는다. 조용히 넘어가지 않는다.
	echo "주의: /etc/duckdns.env가 없어 DuckDNS 갱신을 켜지 않았다." >&2
	echo "      deploy/duckdns.env.example을 보고 만든 뒤 이 스크립트를 다시 돌릴 것." >&2
fi

echo "끝. 확인:"
echo "  systemctl is-active nulbom caddy duckdns.timer"
echo "  sudo journalctl -u nulbom -n 15 --no-pager"
