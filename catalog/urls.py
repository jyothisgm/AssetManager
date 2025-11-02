from django.urls import path
from catalog.autocomplete import CategoryAutocomplete, InstitutionAutocomplete, BrandAutocomplete, StoreAutocomplete, ProductAutocomplete

urlpatterns = [
    path("category-autocomplete/", CategoryAutocomplete.as_view(), name="category-autocomplete"),
    path("institution-autocomplete/", InstitutionAutocomplete.as_view(), name="institution-autocomplete"),
    path("brand-autocomplete/", BrandAutocomplete.as_view(), name="brand-autocomplete"),
    path("store-autocomplete/", StoreAutocomplete.as_view(), name="store-autocomplete"),
    path("product-autocomplete/", ProductAutocomplete.as_view(), name="product-autocomplete"),
]
