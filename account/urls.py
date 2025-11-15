from django.urls import path
from account.autocomplete import AccountAutocomplete
from account.views import AccountExtractionView

urlpatterns = [
    path("account-autocomplete/", AccountAutocomplete.as_view(), name="account-autocomplete"),
    path("extract/", AccountExtractionView.as_view(), name="account-extraction"),
]
