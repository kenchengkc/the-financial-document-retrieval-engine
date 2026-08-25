"""Coarse SIC-code to sector mapping for cross-sectional neutralization.

Maps SEC Standard Industrial Classification codes to ~11 GICS-style sectors.
This is intentionally coarse — enough to remove first-order industry effects
from a signal, not a precise GICS reproduction.
"""

from __future__ import annotations


def sic_to_sector(sic: str | int | None) -> str:
    if sic is None:
        return "Unknown"
    try:
        code = int(str(sic).strip())
    except (TypeError, ValueError):
        return "Unknown"

    # Specific high-value overrides first (pharma, software, autos, real estate).
    if code in (2833, 2834, 2835, 2836) or 3826 <= code <= 3851 or 8000 <= code <= 8099:
        return "Health Care"
    if code in (7372, 7370, 7371, 7373, 7374, 7389) or code in (3571, 3572, 3576, 3577, 3674):
        return "Information Technology"
    if code in (3711, 3713, 3714, 3715, 3711):
        return "Consumer Discretionary"
    if 6500 <= code <= 6599 or code == 6798:
        return "Real Estate"  # real estate operators and REITs

    if 100 <= code <= 999:
        return "Materials"  # agriculture/forestry -> materials proxy
    if 1000 <= code <= 1099 or 1400 <= code <= 1499:
        return "Materials"  # metal/nonmetal mining
    if 1300 <= code <= 1399 or code == 2911:
        return "Energy"  # oil & gas extraction / refining
    if 1500 <= code <= 1799:
        return "Industrials"  # construction
    if 2000 <= code <= 2199:
        return "Consumer Staples"  # food, beverage, tobacco
    if 2200 <= code <= 2399 or 3000 <= code <= 3199:
        return "Consumer Discretionary"  # apparel, textiles, rubber/plastics
    if 2400 <= code <= 2799 or 2800 <= code <= 2999 or 3200 <= code <= 3399:
        return "Materials"  # lumber, paper, chemicals, stone/glass/metals
    if 3400 <= code <= 3599 or 3600 <= code <= 3699 or 3700 <= code <= 3999:
        return "Industrials"  # machinery, electrical, transport equipment, misc
    if 4000 <= code <= 4799:
        return "Industrials"  # transportation
    if 4800 <= code <= 4899 or 7800 <= code <= 7999:
        return "Communication Services"  # telecom, motion pictures, entertainment
    if 4900 <= code <= 4999:
        return "Utilities"
    if 5000 <= code <= 5199:
        return "Industrials"  # wholesale
    if 5200 <= code <= 5999 or 7000 <= code <= 7299 or 5800 <= code <= 5899:
        return "Consumer Discretionary"  # retail, hotels, personal services
    if 6000 <= code <= 6499 or 6700 <= code <= 6799:
        return "Financials"
    if 7300 <= code <= 7399 or 8100 <= code <= 8999:
        return "Industrials"  # business / professional services
    return "Unknown"
