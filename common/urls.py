from django.urls import path
from common.autocomplete import CurrencyAutocomplete, UnitAutocomplete


urlpatterns = [
    path("currency-autocomplete/", CurrencyAutocomplete.as_view(), name="currency-autocomplete"),
    path("unit-autocomplete/", UnitAutocomplete.as_view(), name="unit-autocomplete"),
]
