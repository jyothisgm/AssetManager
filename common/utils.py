from common.models import Unit
from django.db.models import Q
from common.logging_config import logger


def get_or_create_unit(name: str):
    """Return existing Unit (case-insensitive), else create a new one."""
    func_name = "get_or_create_unit"
    try:
        if not name:
            logger.debug(f"[{func_name}] No name provided → returning None")
            return None

        logger.debug(f"[{func_name}] Searching for unit with name or symbol='{name}' (case-insensitive)")
        unit = Unit.objects.filter(Q(name__iexact=name) | Q(symbol__iexact=name)).first()
        if unit:
            if unit.preferred:
                unit = unit.preferred
            logger.info(f"[{func_name}] Found existing unit: {unit}")
        else:
            logger.warning(f"[{func_name}] Unit not found for '{name}'")
        return unit
    except Exception as e:
        logger.warning(f"[{func_name}] Error retrieving or creating unit for name='{name}'", exc_info=True)
        raise e


def convert_quantity(value: float, from_unit, to_unit) -> float:
    """
    Convert a quantity between two compatible units based on Unit model relationships.
    - Handles conversion via each unit's base_unit and conversion_to_base factor.
    - Returns the converted value if compatible, else raises ValidationError.
    """
    func_name = "convert_quantity"
    try:
        if not from_unit or not to_unit or not value:
            logger.debug(f"[{func_name}] Missing input(s): value={value}, from={from_unit}, to={to_unit}")
            return value

        if from_unit.id == to_unit.id:
            logger.debug(f"[{func_name}] Same unit ({from_unit}) → no conversion needed")
            return value

        if from_unit.category != to_unit.category:
            msg = f"⚠️ Conversion skipped: category mismatch ({from_unit.category} → {to_unit.category})"
            logger.warning(f"[{func_name}] {msg}")
            return value, msg

        if not from_unit.conversion_to_base or not to_unit.conversion_to_base:
            msg = f"⚠️ Conversion skipped: missing conversion factors for {from_unit.name} or {to_unit.name}"
            logger.warning(f"[{func_name}] {msg}")
            return value, ''

        # Step 1️⃣: Convert from source to base
        if from_unit.base_unit:
            base_value = value * from_unit.conversion_to_base
            logger.debug(f"[{func_name}] Converted {value} {from_unit.symbol or from_unit.name} → base {base_value}")
        else:
            base_value = value
            logger.debug(f"[{func_name}] Source unit already base → base_value={base_value}")

        # Step 2️⃣: Convert from base to target
        if to_unit.base_unit:
            converted_value = base_value / to_unit.conversion_to_base
            logger.debug(f"[{func_name}] Converted base {base_value} → {converted_value} {to_unit.symbol or to_unit.name}")
        else:
            converted_value = base_value
            logger.debug(f"[{func_name}] Target unit already base → converted_value={converted_value}")

        logger.info(
            f"[{func_name}] Conversion successful: {value} {from_unit.symbol or from_unit.name} → "
            f"{converted_value} {to_unit.symbol or to_unit.name}"
        )
        return converted_value, ''
    except Exception as e:
        logger.exception(f"[{func_name}] Error during conversion value={value}, from={from_unit}, to={to_unit}")
        raise e
