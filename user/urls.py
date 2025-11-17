from django.urls import path
from user.autocomplete import UserAutocomplete

urlpatterns = [
    path("user-autocomplete/", UserAutocomplete.as_view(), name="user-autocomplete"),
]

