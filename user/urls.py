from django.urls import path
from .views import GmailConnectView, GmailCallbackView

urlpatterns = [
    path("gmail_connect/", GmailConnectView.as_view(), name="gmail_connect"),
    path("gmail_callback/", GmailCallbackView.as_view(), name="gmail_callback")
]
