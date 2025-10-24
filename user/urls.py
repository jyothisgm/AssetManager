from django.urls import path
from user import admin_views

urlpatterns = [
    path('admin/my-profile/', admin_views.my_profile_view, name='my_profile'),
]
