from dal import autocomplete
from account.models import Account


class AccountAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Account.objects.filter(created_by=self.request.user)
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs
