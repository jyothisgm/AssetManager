from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Role

admin.site.site_header = "Asset Manager Admin"
admin.site.site_title = "Asset Manager Portal"
admin.site.index_title = "Welcome to the Asset Manager Dashboard"
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Roles & Permissions", {"fields": ("roles", "is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"fields": ("email", "password1", "password2")}),)
    list_display = ("email", "is_staff", "is_superuser")
    search_fields = ("email",)
    ordering = ("email",)

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
