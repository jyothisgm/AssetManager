from common.models import Unit
from django.db.models import Q


def get_or_create_unit(name: str):
    """Return existing Unit (case-insensitive), else create a new one."""
    if not name:
        return None
    unit = Unit.objects.filter(Q(name__iexact=name) | Q(symbol__iexact=name)).first()    
    return unit


def convert_quantity(value: float, from_unit, to_unit) -> float:
    """
    Convert a quantity between two compatible units based on Unit model relationships.
    - Handles conversion via each unit's base_unit and conversion_to_base factor.
    - Returns the converted value if compatible, else raises ValidationError.
    """
    if not from_unit or not to_unit or not value:
        return value

    # Check for same object (no conversion needed)
    if from_unit.id == to_unit.id:
        return value

    # Check same category (e.g. both are 'weight')
    if from_unit.category != to_unit.category:
        print(f"⚠️ Conversion skipped: category mismatch ({from_unit.category} → {to_unit.category})")
        return value, f"⚠️ Conversion skipped: category mismatch ({from_unit.category} → {to_unit.category})"

    # Ensure both have valid conversion paths
    if not from_unit.conversion_to_base or not to_unit.conversion_to_base:
        print(f"⚠️ Conversion skipped: missing conversion factors for {from_unit.name} or {to_unit.name}")
        return value, ''

    # Step 1️⃣: Convert from source to base
    if from_unit.base_unit:
        base_value = value * from_unit.conversion_to_base
    else:
        base_value = value  # already base

    # Step 2️⃣: Convert from base to target
    if to_unit.base_unit:
        converted_value = base_value / to_unit.conversion_to_base
    else:
        converted_value = base_value  # already base

    return converted_value, ''
