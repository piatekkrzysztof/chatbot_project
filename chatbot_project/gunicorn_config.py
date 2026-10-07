"""Profil 512 MiB. Użycie: gunicorn -c python:chatbot_project.gunicorn_config."""

from chatbot_project import pojemnosc

wsgi_app = "chatbot_project.wsgi:application"
workers = 1
worker_class = "gthread"
# Rozmowy + upload + wątki na panel; zmiana limitów zmienia też wątki.
threads = pojemnosc.WATKI
timeout = 30
# Daj aktywnej rozmowie czas na zakończenie przy łagodnym restarcie.
# Platforma hostingowa może mieć krótszy własny termin SIGKILL.
graceful_timeout = 100
