from django.contrib.admin.apps import AdminConfig


class MFAAdminConfig(AdminConfig):
    default_site = "accounts.admin_security.MFAAdminSite"
