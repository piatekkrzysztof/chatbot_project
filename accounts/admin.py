from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Tenant, CustomUser, InvitationToken, Subscription


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = (
        "name", "gpt_prompt", "subscription_status", "current_token_usage",
        "token_limit", "data_retention_days",
    )
    list_filter = ("data_retention_days",)
    search_fields = ("name",)
    readonly_fields = ("api_key", "created_at")


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ("username", "email", "tenant", "role", "is_staff")
    list_filter = ("role", "tenant")
    fieldsets = UserAdmin.fieldsets + (
        ("Tenant", {"fields": ("tenant", "role")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Tenant", {"fields": ("tenant", "role")}),
    )


admin.site.register(Subscription)


@admin.register(InvitationToken)
class InvitationTokenAdmin(admin.ModelAdmin):
    list_display = ("email", "tenant", "role", "duration", "users", "max_users", "is_valid_token", "expires_at")
    readonly_fields = ("token", "created_at", "expires_at")
    list_filter = ("role", "duration")

    def is_valid_token(self, obj):
        return obj.is_valid()

    is_valid_token.boolean = True
