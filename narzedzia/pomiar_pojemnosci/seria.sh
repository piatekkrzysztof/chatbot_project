#!/bin/sh
# Wariant: WATKI ROZMOWY NA_FIRME
PY="C:/Users/krzys/Desktop/chatbot_project/venv/Scripts/python.exe"
cd "$(dirname "$0")"
W=$1; R=$2; F=$3
sh uruchom.sh $W $R $F 1 >/dev/null
T="${W}w-${R}r-${F}f"
"$PY" obciazenie.py 2 2 0 "$T rozgrzewka" >/dev/null
"$PY" obciazenie.py $R 1 0 "$T jedna-firma" >/dev/null
"$PY" obciazenie.py $R 4 0 "$T cztery-firmy" >/dev/null
"$PY" obciazenie.py $R 4 1 "$T z-uploadem" >/dev/null
"$PY" obciazenie.py $((R+4)) 4 1 "$T nadmiar+upload" >/dev/null
echo "$T gotowe"
