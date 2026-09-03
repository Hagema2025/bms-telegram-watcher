# chennai_venues.py
"""
Static, editable list of Chennai cinema venue names.

Why static instead of scraped: BookMyShow doesn't have a reliable page
listing every Chennai cinema, and probing guessed URLs risks tripping
Cloudflare's bot protection (as we saw). A maintained list sidesteps
that entirely, and lets you pick exactly the venues you care about.

HOW TO EDIT:
Just add/remove/rename strings in the list below. Names don't need to be
exact -- matching against the live BMS page is done as a case-insensitive
substring check, so "Sathyam" will match "PVR: Sathyam, Royapettah" etc.
If a venue you want isn't firing correctly, try a shorter/more distinctive
fragment of its name (e.g. "Sathyam" rather than the full official name).
"""

CHENNAI_VENUES = [
    "PVR: Sathyam, Chennai",
    "PVR: Escape, Chennai",
    "PVR: Heritage RSL ECR, Chennai",
    "PVR: Palazzo, Chennai",
    "PVR: VR Chennai, Anna Nagar",
    "PVR: Ampa, Chennai",
    "PVR: Grand Galada, Chennai",
    "INOX: The Marina Mall, OMR",
    "INOX: Chennai Citi Centre",
    "INOX: Luxe, Phoenix Marketcity",
    "Cinepolis: BSR Mall, OMR, Thoraipakkam",
    "Cinepolis: AGS Cinemas, Chennai",
    "AGS Cinemas: T. Nagar",
    "AGS Cinemas: Villivakkam",
    "Rohini SilverScreens, Chennai",
    "Kamala Cinemas, Chennai",
    "GK Cinemas, Chennai",
    "Mayajaal Multiplex, Chennai",
    "Luxe Cinemas, Chennai",
    "SPI Cinemas, Chennai",
]