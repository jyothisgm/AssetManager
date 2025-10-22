from django.core.management.base import BaseCommand
from catalog.models import Institution

class Command(BaseCommand):
    help = "Populate Institution table with common financial entities"

    def handle(self, *args, **options):
        defaults = [
            ("ING Bank", "ING", "bank", "Netherlands", "https://www.ing.nl/"),
            ("ABN AMRO", "ABN AMRO", "bank", "Netherlands", "https://www.abnamro.nl/"),
            ("Rabobank", "Rabobank", "bank", "Netherlands", "https://www.rabobank.nl/"),
            ("Revolut", "Revolut", "fintech", "UK", "https://www.revolut.com/"),
            ("DEGIRO", "DEGIRO", "broker", "Netherlands", "https://www.degiro.nl/"),
        ]
        for name, short, typ, country, site in defaults:
            Institution.objects.get_or_create(
                name=name,
                defaults={"short_name": short, "type": typ, "country": country, "website": site},
            )
        self.stdout.write(self.style.SUCCESS("✅ Institutions seeded successfully"))
