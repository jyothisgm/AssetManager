from dal import autocomplete
from catalog.models import Brand, Institution, Product, Store, PurchaseCategory


class CategoryAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = PurchaseCategory.objects.all()
        if self.q:
            qs = qs.filter(name__icontains=self.q) | qs.filter(group__name__icontains=self.q)
        return qs


class InstitutionAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Institution.objects.all()
        if self.q:
            qs = qs.filter(name__icontains=self.q) | qs.filter(short_name__icontains=self.q)
        return qs


class BrandAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Brand.objects.all()
        if self.q:
            qs = qs.filter(name__icontains=self.q) | qs.filter(preferred__name__icontains=self.q)
        return qs


class ProductAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Product.objects.filter(preferred=None)
        if self.q:
            qs = qs.filter(name__icontains=self.q) | qs.filter(preferred__name__icontains=self.q)
        return qs


class StoreAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Store.objects.filter(preferred=None)
        if self.q:
            qs = qs.filter(name__icontains=self.q) | qs.filter(preferred__name__icontains=self.q)
        return qs
