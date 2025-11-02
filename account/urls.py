from django.urls import path
from account.autocomplete import AccountAutocomplete

urlpatterns = [
    path("account-autocomplete/", AccountAutocomplete.as_view(), name="account-autocomplete"),
]
