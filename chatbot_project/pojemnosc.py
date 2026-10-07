"""
Ile ciężkich żądań naraz obsługuje jeden proces web.

Wspólne dla Django (api/capacity.py) i Gunicorna (gunicorn_config.py), żeby
liczba wątków zawsze zostawiała miejsce nad rozmowami i uploadem. Gunicorn
czyta ten plik przed załadowaniem Django, więc tu nie ma importu ustawień.

Liczby z pomiaru 7.10.2026 na kontenerze jak produkcja: 512 MiB, 0,5 CPU,
prawdziwy klient OpenAI na atrapie API ([opis](../docs/pojemnosc-http.md)).
Ogranicza procesor, nie pamięć: rozmowa dokłada około 1 MiB, ale przy 10
naraz pierwszy fragment odpowiedzi zbliżał się do 3 s, a panel do sekundy.
Przy 6 naraz z uploadem w tle pierwszy fragment mieścił się w 2,3 s.
"""

import os

#: Rozmowy naraz w procesie - wszystkie firmy i wszystkie drogi czatu.
ROZMOWY = int(os.getenv("POJEMNOSC_ROZMOW", "6"))
#: Ile z nich może zająć jedna firma. Reszta zostaje dla pozostałych klientów.
ROZMOWY_FIRMY = int(os.getenv("POJEMNOSC_ROZMOW_FIRMY", "3"))
#: Uploady naraz. Rezerwa pamięci parsera (documents/isolated_parser.py)
#: zakłada jeden.
UPLOADY = int(os.getenv("POJEMNOSC_UPLOADOW", "1"))
#: Wątki ponad ciężkie żądania: panel ładuje kilka list naraz, do tego
#: odczyty widgetu i health.
WATKI_LEKKIE = 3
WATKI = ROZMOWY + UPLOADY + WATKI_LEKKIE
