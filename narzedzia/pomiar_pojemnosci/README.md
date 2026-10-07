# Pomiar pojemności procesu web

Powtarza pomiar z 7.10.2026 ([opis i wyniki](../../docs/pojemnosc-http.md)).
Lokalnie, w Dockerze, bez kosztów: OpenAI zastępuje atrapa API, a aplikacja
używa prawdziwego klienta `openai`. Nie łączy się z produkcją.

1. Zbuduj obraz z bieżącego kodu:
   `docker build --target production -t saas-pomiar-20261007 .`
2. Sieć, baza, Redis i atrapa (nazwy z sufiksem daty, osobno od innych projektów):

   ```sh
   docker network create pomiar-20261007
   docker run -d --name pomiar-20261007-db --network pomiar-20261007 \
     -e POSTGRES_PASSWORD=pomiar -e POSTGRES_DB=pomiar pgvector/pgvector:pg16
   docker run -d --name pomiar-20261007-redis --network pomiar-20261007 redis:8-alpine
   docker run -d --name pomiar-20261007-openai --network pomiar-20261007 \
     -v "$PWD/narzedzia/pomiar_pojemnosci:/pomiar:ro" --entrypoint python \
     saas-pomiar-20261007 /pomiar/atrapa_openai.py
   ```

3. Utwórz `env.list` obok skryptów (plik jest w `.gitignore`):

   ```
   DJANGO_SETTINGS_MODULE=chatbot_project.settings.pomiar
   DATABASE_URL=postgres://postgres:pomiar@pomiar-20261007-db:5432/pomiar
   DJANGO_SECRET_KEY=<dowolny losowy ciąg, tylko lokalnie>
   OPENAI_API_KEY=atrapa
   OPENAI_BASE_URL=http://pomiar-20261007-openai:9000/v1
   REDIS_URL=redis://pomiar-20261007-redis:6379/0
   FRONTEND_URL=http://localhost:3000
   OPENBLAS_NUM_THREADS=1
   ```

4. Profil z repozytorium: `sh uruchom_domyslne.sh` - sam wykonuje migracje
   i zakłada cztery syntetyczne firmy. Potem warianty:
   `sh seria.sh WATKI ROZMOWY NA_FIRME`.
5. Jeden scenariusz: `python obciazenie.py ROZMOWY FIRMY UPLOAD(0/1) ETYKIETA`,
   panel po kilka żądań naraz: `PANEL_ROWNOLEGLE=5`. Wyniki w `wyniki.jsonl`.

Pamięć skrypt czyta z cgroup v1 (Docker Desktop). Na hoście z cgroup v2
zamień ścieżki na `memory.current` i `memory.stat` (`anon`, `file`).
Sprzątanie: `docker rm -f` czterech kontenerów `pomiar-20261007-*`
i `docker network rm pomiar-20261007`.
