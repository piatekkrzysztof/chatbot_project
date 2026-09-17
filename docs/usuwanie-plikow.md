# Pliki znikają razem z danymi (F18, część 1)

Stan na 17.09.2026, wersja 2.8.1. Pierwsza część F18 z
[roadmapy](roadmapa-po-audycie.md): spójne usuwanie pochodnych. Dotyczy
plików w magazynie, nie okresów przechowywania - **ten dokument nie włącza
żadnego nowego automatycznego usuwania danych**, zgodnie z zastrzeżeniem
z [przepływów danych](przeplywy-danych.md#dlaczego-bez-nowego-usuwania).

## Po co

Baza danych i magazyn plików to dwa różne miejsca. Usunięcie wiersza zabiera
ze sobą wiersze powiązane (kaskada), ale o pliku w R2 nie wie nic. Do wersji
2.8.0 plik kasowało jedno miejsce w kodzie: widok, który obsługuje przycisk
„Usuń" w panelu. Każda inna droga zostawiała plik w magazynie **bez żadnego
wiersza, który by do niego prowadził** - czyli bez szansy, że ktoś go kiedyś
znajdzie i skasuje.

To nie jest tylko rachunek za miejsce. Treść, którą klient kazał usunąć,
leżała dalej w naszym magazynie, a panel pokazywał, że dokumentu nie ma.

## Co było nieszczelne

| Droga | Co zostawało | Kto tak robi |
|---|---|---|
| Panel administracyjny Django | plik dokumentu | my, przy zgłoszeniu klienta |
| Usunięcie firmy (kaskada) | pliki wszystkich jej dokumentów | żądanie „usuńcie moje dane" |
| `Document.objects.filter(...).delete()` | pliki wszystkich objętych dokumentów | sprzątanie z powłoki |
| Wymiana logo albo awatara widgetu | poprzedni obraz | klient, przy każdej poprawce logo |
| Usunięcie firmy | logo i awatar | jak wyżej |

Każda z tych dróg ma teraz czerwony test na kodzie sprzed zmiany
(`documents/tests/test_usuwanie_pochodnych.py`).

## Jak to działa teraz

Kasowanie pliku wisi na **sygnale usunięcia wiersza**, a nie na przycisku
w panelu. `post_delete` dostaje każdy usunięty wiersz - także z kaskady
i z `queryset.delete()`, które nie wołają `Model.delete()` w ogóle. Nadpisana
metoda modelu nie objęłaby ani jednej z dwóch ostatnich dróg z tabeli wyżej.

Wspólna zasada dla wszystkich plików siedzi w `chatbot_project/pliki.py`
i sprowadza się do dwóch zdań:

1. **Kasujemy po zatwierdzeniu transakcji**, nie w jej trakcie. Magazyn nie
   bierze udziału w transakcji bazy, więc wycofanie przywróci wiersz, ale nie
   przywróci pliku - kopii nie trzymamy. Pilnuje tego test, który usuwa
   dokument i wycofuje transakcję: wiersz wraca, plik ma zostać.
2. **Błąd magazynu niczego nie przerywa.** Wiersz jest już wtedy usunięty
   i cofnąć się go nie da, a magazyn bywa niedostępny, bo jest po sieci.
   Zostaje wpis w logu z nazwą pliku, żeby dało się go odnaleźć później.

Dwa przypadki, w których plik ma **nie** zniknąć:

- **Odtwarzanie kopii zapasowej.** `loaddata` wgrywa wiersze obok
  przywracanych plików, więc nazwa „poprzedniego" obrazu to nazwa pliku,
  który właśnie odtworzyliśmy. Sygnał wychodzi przy `raw=True` - tak samo jak
  sygnał embeddingów, który przy pierwszej próbie odtworzenia zlecał płatne
  liczenie wektorów dla całej bazy.
- **Zapis firmy, który obrazów nie dotyczy.** Porównanie z poprzednią wersją
  kosztuje jedno zapytanie, więc pytamy tylko przy zapisie obejmującym logo
  albo awatar. Zwykła zmiana ustawień widgetu nie kosztuje nic - sprawdza to
  test liczby zapytań.

Podstrony pobrane z witryny klienta nie mają pliku i jest ich najwięcej (do 20
na źródło). Ich usunięcie nie może zostawiać śladu w logu, bo zalałoby go przy
każdym odświeżeniu witryny; osobny test pilnuje, że log zostaje pusty.

## Weryfikacja

- Testy na kodzie sprzed zmiany: 6 czerwonych przypadków (usunięcie dokumentu,
  usunięcie firmy, usunięcie hurtem, logo i awatar firmy, wymiana logo, błąd
  magazynu).
- Mutacje: 9 z 9 złapanych, w tym kasowanie bez czekania na zatwierdzenie
  transakcji, brak wyjścia przy odtwarzaniu kopii i odłączenie sygnałów
  w `AccountsConfig.ready()`.
- Test podłączenia sygnałów startuje Django w osobnym procesie, tak jak web
  i worker. Sygnał dokumentów zniknął już raz z `ready()` w porządkach ruff
  (PR #21) i nikt tego nie zauważył przez tydzień; teraz na tej samej liście
  wisi kasowanie plików.

## Co zostaje

1. **Pliki osierocone wcześniej.** Wszystko, co zostało w magazynie przed tą
   poprawką, dalej tam leży - żaden wiersz do tego nie prowadzi, więc nowa
   zasada ich nie dotknie. Potrzebny jest raport: lista obiektów w magazynie
   bez odpowiadającego wiersza, z rozmiarem i datą. **Najpierw sam raport**,
   bez kasowania: usuwanie czegokolwiek hurtem z produkcji ma sens dopiero po
   odbiorze pełnego odtworzenia z kopii (F21).
2. **Limity wiedzy** - druga połowa F18. Limit planu liczy długość
   wyodrębnionego tekstu wszystkich dokumentów firmy
   (`documents/validators.py`), a nie rozmiar plików. Do sprawdzenia, czy po
   obniżeniu planu klient z bazą większą niż nowy limit zachowuje się tak, jak
   chcemy.
