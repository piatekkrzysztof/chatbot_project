#!/bin/sh
# Użycie: uruchom.sh WATKI ROZMOWY ROZMOWY_FIRMY UPLOADY
# Kontener web jak produkcja: 512 MiB bez swapu, 0,5 CPU, profil gunicorna z repo.
set -e
P="$(cd "$(dirname "$0")" && pwd -W 2>/dev/null || pwd)"
docker rm -f pomiar-20261007-web >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 docker run -d --name pomiar-20261007-web --network pomiar-20261007 \
  --memory=512m --memory-swap=512m --cpus=0.5 -p 18000:8000 \
  --tmpfs /tmp:rw,size=64m,uid=10001 \
  --env-file "$P/env.list" \
  -e GUNICORN_CMD_ARGS="--threads $1" \
  -e POJEMNOSC_ROZMOW="$2" -e POJEMNOSC_ROZMOW_FIRMY="$3" -e POJEMNOSC_UPLOADOW="$4" \
  -v "$P/pomiar_settings.py:/app/chatbot_project/settings/pomiar.py:ro" \
  saas-pomiar-20261007 >/dev/null
for i in $(seq 1 60); do
  if curl -s -o /dev/null -w '%{http_code}' http://localhost:18000/api/widget/faq/ 2>/dev/null | grep -q '[0-9]'; then break; fi
  sleep 1
done
MSYS_NO_PATHCONV=1 docker run --rm --network pomiar-20261007 --env-file "$P/env.list" \
  -v "$P/pomiar_settings.py:/app/chatbot_project/settings/pomiar.py:ro" -v "$P:/pomiar:ro" \
  saas-pomiar-20261007 sh -c "python manage.py shell < /pomiar/dane.py" 2>/dev/null \
  | grep '^DANE=' | sed 's/^DANE=//' > "$P/dane.json"
docker logs pomiar-20261007-web 2>&1 | grep -E "Using worker|Booting worker" | head -3
