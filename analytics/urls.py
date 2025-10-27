from django.contrib import admin
from django.urls import path
from analytics.admin import AnalyticsAdminSite

admin_site = AnalyticsAdminSite(name="analytics_admin")

urlpatterns = [
    path("admin/", admin_site.urls),
]
