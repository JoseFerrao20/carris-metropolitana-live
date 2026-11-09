#!/usr/bin/env bash
# Instala (ou atualiza) o Carris Metropolitana Live numa VM Ubuntu (testado para Oracle Cloud
# Always Free, ARM). Idempotente: correr outra vez faz git pull e reconstrói.
#
#   sudo bash deploy/install.sh
#
# Variáveis opcionais: SITE_ADDRESS (por omissão <ip-público>.sslip.io), REPO, BRANCH, DIR.
set -euo pipefail

REPO="${REPO:-https://github.com/JoseFerrao20/carris-metropolitana-live.git}"
BRANCH="${BRANCH:-main}"
DIR="${DIR:-/opt/cmlive}"
COMPOSE=(docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml)

log() { printf '\n==> %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Corra como root (sudo)." >&2; exit 1; }

log "Pacotes (Docker, Compose, git)"
export DEBIAN_FRONTEND=noninteractive
if ! docker compose version >/dev/null 2>&1; then
  apt-get update -q
  apt-get install -y -q docker.io docker-compose-v2 docker-buildx git curl
fi
systemctl enable --now docker

log "Firewall da VM: abrir 80 e 443"
# As imagens Ubuntu da Oracle trazem regras iptables que rejeitam tudo exceto SSH.
if command -v iptables >/dev/null && ! iptables -C INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT 2>/dev/null; then
  iptables -I INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT
  command -v netfilter-persistent >/dev/null && netfilter-persistent save || true
fi
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then ufw allow 80,443/tcp; fi

log "Memória: swap de 2 GB se houver pouca RAM (o build do frontend precisa)"
if [ "$(awk '/MemTotal/ {print int($2/1024/1024)}' /proc/meminfo)" -lt 8 ] && ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

log "Código em $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" reset -q --hard "origin/$BRANCH"
else
  git clone -q --depth 50 --branch "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

log "Configuração (.env)"
touch .env && chmod 600 .env
if ! grep -q '^POSTGRES_PASSWORD=' .env; then
  # Gerada uma vez; o volume da BD fica com esta password.
  echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)" >> .env
fi
if ! grep -q '^SITE_ADDRESS=' .env; then
  if [ -z "${SITE_ADDRESS:-}" ]; then
    ip="$(curl -fsS --max-time 10 https://api.ipify.org || curl -fsS --max-time 10 https://ifconfig.me)"
    SITE_ADDRESS="${ip//./-}.sslip.io" # ex.: 203-0-113-10.sslip.io resolve para 203.0.113.10
  fi
  echo "SITE_ADDRESS=$SITE_ADDRESS" >> .env
fi
SITE="$(grep '^SITE_ADDRESS=' .env | cut -d= -f2-)"

log "Build e arranque (a primeira vez demora ~10 min numa VM ARM pequena)"
"${COMPOSE[@]}" up -d --build --remove-orphans

log "GTFS atualizado todos os dias às 05:17 (só recarrega se o ficheiro mudou)"
cat > /etc/cron.d/cmlive-gtfs <<EOF
17 5 * * * root cd $DIR && ${COMPOSE[*]} run --rm gtfs >> /var/log/cmlive-gtfs.log 2>&1
EOF

log "Pronto"
echo "Site: https://$SITE   (o certificado HTTPS pode demorar 1-2 min na primeira vez)"
echo "Estado: cd $DIR && ${COMPOSE[*]} ps"
echo "Logs:   cd $DIR && ${COMPOSE[*]} logs -f --tail=50 collector web"
