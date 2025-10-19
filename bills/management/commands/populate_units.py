from django.core.management.base import BaseCommand
from bills.models import Unit

class Command(BaseCommand):
    help = "Populate Unit table with canonical definitions and conversions for weight, length, volume, and pieces"

    def handle(self, *args, **options):
        self.stdout.write("📦 Populating Unit table...")

        # ------------------------------------------
        # 1️⃣ Base canonical units (category roots)
        # ------------------------------------------
        base_definitions = {
            "weight": [
                ("Gram", "g", 1.0),
                ("Kilogram", "kg", 1000.0),
            ],
            "length": [
                ("Metre", "m", 1.0),
                ("Centimetre", "cm", 0.01),
                ("Millimetre", "mm", 0.001),
            ],
            "volume": [
                ("Millilitre", "ml", 1.0),
                ("Litre", "L", 1000.0),
            ],
            "pieces": [
                ("Piece", "pcs", 1.0),
                ("Packet", "pkt", 1.0),
                ("Dozen", "doz", 12.0),
            ],
        }

        for category, defs in base_definitions.items():
            for name, symbol, factor in defs:
                base_unit = None
                if category == "weight" and name == "Kilogram":
                    base_unit = Unit.objects.filter(name="Gram").first()
                elif category == "length" and name in ["Centimetre", "Millimetre"]:
                    base_unit = Unit.objects.filter(name="Metre").first()
                elif category == "volume" and name == "Litre":
                    base_unit = Unit.objects.filter(name="Millilitre").first()
                elif category == "pieces" and name in ["Packet", "Dozen"]:
                    base_unit = Unit.objects.filter(name="Piece").first()

                unit, _ = Unit.objects.get_or_create(
                    name=name,
                    defaults={
                        "symbol": symbol,
                        "category": category,
                        "base_unit": base_unit,
                        "conversion_to_base": factor,
                    },
                )
                unit.category = category
                unit.base_unit = base_unit
                unit.conversion_to_base = factor
                unit.save()

        # ------------------------------------------
        # 2️⃣ Variant spellings (aliases)
        # ------------------------------------------
        variants = {
            "Gram": ["gm", "grams", "gramme", "gr", "gms"],
            "Kilogram": ["Kg.", "Kgs", "kilo", "kilogramme"],
            "Metre": ["meter", "meters", "metres"],
            "Centimetre": ["cms", "centimeter", "centimetres"],
            "Millimetre": ["millimeter", "millimeters", "millimetre"],
            "Millilitre": ["ml.", "milliliter", "millilitres", "mL"],
            "Litre": ["Liter", "Liters", "litre", "ltr", "lt", "Ltr"],
            "Piece": ["pc", "piece", "pieces", "unit", "pcs"],
            "Packet": ["pack", "packet", "packets"],
            "Dozen": ["dz", "dozen"],
        }

        for canonical_name, alias_list in variants.items():
            try:
                canonical = Unit.objects.get(name=canonical_name)
            except Unit.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"⚠️ Skipped missing canonical: {canonical_name}"))
                continue

            for alias in alias_list:
                alias_unit, _ = Unit.objects.get_or_create(
                    name=alias,
                    defaults={
                        "symbol": alias,
                        "category": canonical.category,
                        "base_unit": canonical.base_unit or canonical,
                        "conversion_to_base": canonical.conversion_to_base,
                    },
                )
                alias_unit.preferred = canonical
                alias_unit.category = canonical.category
                alias_unit.base_unit = canonical.base_unit or canonical
                alias_unit.conversion_to_base = canonical.conversion_to_base
                alias_unit.save()

        # ------------------------------------------
        # 3️⃣ Sanity check (repair orphaned units)
        # ------------------------------------------
        for unit in Unit.objects.all():
            if unit.category not in ["weight", "length", "volume", "pieces"]:
                unit.category = "pieces"  # default fallback
                unit.save(update_fields=["category"])
            if not unit.conversion_to_base:
                unit.conversion_to_base = 1.0
                unit.save(update_fields=["conversion_to_base"])

        self.stdout.write(self.style.SUCCESS("✅ Unit table populated and normalized successfully!"))
