"""Granica obsługi aplikacji, nie zalecenie okresu przechowywania danych."""

MAX_RETENTION_DAYS = 3650


def poprawne_dni(value):
    return type(value) is int and 0 <= value <= MAX_RETENTION_DAYS
