"""Profil 512 MiB. Użycie: gunicorn -c python:chatbot_project.gunicorn_config."""

wsgi_app = "chatbot_project.wsgi:application"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 30
# Daj aktywnej rozmowie czas na zakończenie przy łagodnym restarcie.
# Platforma hostingowa może mieć krótszy własny termin SIGKILL.
graceful_timeout = 100
