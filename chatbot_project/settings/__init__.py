import os

env = os.environ.get("DJANGO_ENV", "dev")  # domyślnie dev

if env == "prod":
    from .prod import *
else:
    from .dev import *
