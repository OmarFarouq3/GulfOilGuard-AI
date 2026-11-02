"""Small unit helpers. The project uses km, hours and metres per second."""

M_PER_S_TO_KM_PER_H = 3.6


def m_per_s_to_km_per_h(speed_m_per_s: float) -> float:
    return speed_m_per_s * M_PER_S_TO_KM_PER_H


def km_to_metres(distance_km: float) -> int:
    """Whole metres, because OR-Tools only accepts integers."""
    return int(round(distance_km * 1000))


def volume_to_units(volume_m3: float, scale: int) -> int:
    """Oil volume as a whole number (scale=10 means tenths of a m3)."""
    return int(round(volume_m3 * scale))


def travel_hours(distance_km: float, speed_m_per_s: float) -> float:
    return distance_km / m_per_s_to_km_per_h(speed_m_per_s)
