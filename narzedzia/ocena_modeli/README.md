# Porównanie modeli czatu

Powtarza pomiar z [docs/wybor-modelu.md](../../docs/wybor-modelu.md) - na
przykład gdy OpenAI wyda nowy model albo zmieni ceny.

```sh
python narzedzia/ocena_modeli/ocena.py gpt-4o-mini "gpt-6-luna|medium"
python narzedzia/ocena_modeli/ocena.py "gpt-6-luna|low" "gpt-6-luna|high" --powtorzenia 3
```

- Klucz OpenAI z lokalnego `.env`. Koszt: kilka centów na model.
- Baza lokalna; firma i dokumenty testowe w transakcji wycofywanej na końcu.
- `model|wartość` - z takim `reasoning_effort`. Temperatura 0,2 idzie tylko
  do modeli, które ją przyjmują.
- `dokumenty/` - cztery pliki testowe z danymi fikcyjnymi: cennik DOCX
  z tabelą, zasady przechowywania TXT w Windows-1250, regulamin PDF i oferta
  cateringu PDF.
- Ceny w `CENY` są z 8.10.2026 - przed porównaniem sprawdź aktualny cennik
  OpenAI. Model spoza listy dostaje koszt „?”.

Druga bramka, ten sam pomiar co CI na zamrożonym korpusie, ale z prawdziwym
modelem: `python manage.py ocen_generowanie --model NAZWA`.
