from django.urls import path
from .views import EmailSyncStatusView, ScanAllEmailsView

urlpatterns = [
    path("scan-emails/", ScanAllEmailsView.as_view(), name="scan_all_emails"),
    path("sync-status/", EmailSyncStatusView.as_view(), name="sync_status"),
]
