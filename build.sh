#!/usr/bin/env bash
#
# Skrypt budowania na Renderze.
#
# errexit jest tu kluczowy: bez niego nieudany `pip install` nie przerywał
# skryptu. collectstatic i tak przechodził (Django było już zainstalowane),
# a build wywracał się dopiero na `migrate` — z komunikatem o brakującym
# module zamiast o brakującej instalacji. Prawdziwa przyczyna zostawała
# kilkaset linii wyżej w logu i wyglądało to na awarię migracji.
set -o errexit
set -o pipefail
set -o nounset

echo "==> [1/3] Instalacja zależności"
pip install -r requirements.txt

echo "==> [2/3] Pliki statyczne"
python manage.py collectstatic --noinput

echo "==> [3/3] Migracje bazy danych"
python manage.py migrate

echo "==> Build zakończony poprawnie"
