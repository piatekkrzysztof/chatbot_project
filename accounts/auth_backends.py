"""
Logowanie adresem e-mail albo nazwą użytkownika.

Formularz logowania jest opisany "E-mail", ale Django uwierzytelnia po polu
USERNAME_FIELD, czyli username. Dotąd nikt tego nie zauważył, bo konta zakładane
ręcznie miały username równy adresowi. Pracownik przyjmujący zaproszenie wybiera
własną nazwę użytkownika i jego adres przestaje pasować — czyli osoba zaproszona
do zespołu nie mogła się zalogować tym, o co prosi ją formularz.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


def konta_dla_logowania(nazwa):
    """
    Konta, do których pasuje tekst z pola logowania: najpierw po adresie
    e-mail (bez rozróżniania wielkości liter), potem po nazwie użytkownika.

    Jedna reguła dla logowania i dla limitu prób na konto - inaczej limit
    liczyłby co innego, niż sprawdza logowanie.
    """
    User = get_user_model()
    return list(User.objects.filter(email__iexact=nazwa)[:2]) or list(
        User.objects.filter(username=nazwa)[:2]
    )


class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()

        if username is None:
            username = kwargs.get(User.USERNAME_FIELD) or kwargs.get("email")
        if username is None or password is None:
            return None

        # iexact, bo adresy e-mail bywają wpisywane wielką literą; przy kilku
        # kontach na ten sam adres nie zgadujemy, do którego chodziło
        matches = konta_dla_logowania(username)

        if len(matches) != 1:
            # Ten sam koszt czasowy co przy trafieniu — inaczej różnica w czasie
            # odpowiedzi zdradzałaby, które adresy istnieją w bazie
            User().set_password(password)
            return None

        user = matches[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
