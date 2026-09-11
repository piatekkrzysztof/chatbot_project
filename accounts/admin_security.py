from django import forms
from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.db import transaction
from django.utils.crypto import constant_time_compare
from rest_framework.exceptions import APIException

from accounts import dwuskladnikowe
from accounts.models import CustomUser, DrugiSkladnik
from api.mfa_throttles import MfaThrottle, account_attempt


class MFAAdminForm(AdminAuthenticationForm):
    kod = forms.CharField(
        label="Kod z aplikacji lub kod zapasowy",
        max_length=64,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
    )

    def clean(self):
        try:
            limiter = MfaThrottle()
            if not limiter.allow_request(self.request, None):
                raise forms.ValidationError("Zbyt wiele prób. Spróbuj później.")
            result = super().clean()
            if self.user_cache is None:
                return result
            with transaction.atomic():
                user = CustomUser.objects.select_for_update().get(pk=self.user_cache.pk)
                if (
                    not user.is_active
                    or not user.is_staff
                    or not constant_time_compare(user.password, self.user_cache.password)
                ):
                    raise forms.ValidationError("Zaloguj się ponownie.")
                account_attempt(user)
                factor = DrugiSkladnik.objects.filter(uzytkownik=user).first()
                if not factor or not factor.wlaczony:
                    raise forms.ValidationError(
                        "Najpierw włącz drugi składnik w ustawieniach konta."
                    )
                code = result.get("kod", "")
                if not (
                    dwuskladnikowe.sprawdz_kod(factor, code)
                    or dwuskladnikowe.zuzyj_kod_zapasowy(user, code)
                ):
                    raise forms.ValidationError("Kod jest nieprawidłowy lub został użyty.")
                self.request._admin_mfa = dwuskladnikowe.fingerprint(user, factor)
            return result
        except APIException:
            raise forms.ValidationError(
                "Weryfikacja chwilowo niedostępna. Spróbuj później."
            ) from None


class MFAAdminSite(AdminSite):
    login_form = MFAAdminForm
    login_template = "admin/mfa_login.html"

    def has_permission(self, request):
        if not super().has_permission(request):
            return False
        factor = DrugiSkladnik.objects.filter(uzytkownik=request.user).first()
        return bool(
            factor
            and factor.wlaczony
            and constant_time_compare(
                request.session.get("admin_mfa", ""),
                dwuskladnikowe.fingerprint(request.user, factor),
            )
        )

    def login(self, request, extra_context=None):
        response = super().login(request, extra_context)
        stamp = getattr(request, "_admin_mfa", None)
        if stamp and request.user.is_authenticated:
            request.session["admin_mfa"] = stamp
        response["Cache-Control"] = "no-store"
        return response
