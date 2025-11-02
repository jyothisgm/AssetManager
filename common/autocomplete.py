from dal import autocomplete

from common.models import Currency, Unit


class CurrencyAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Currency.objects.all()
        if self.q:
            qs = qs.filter(name__icontains=self.q) | qs.filter(code__icontains=self.q)
        return qs


class UnitAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Unit.objects.filter(preferred=None)
        if self.q:
            qs = qs.filter(name__icontains=self.q) | qs.filter(code__icontains=self.q)
        return qs
