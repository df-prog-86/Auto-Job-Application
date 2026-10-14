"""
Where places are, so "around Boston" can mean "within 25 miles of Boston" without asking an AI each time.

Coordinates come from two places:
  * a small built-in table of large cities and the greater Boston area (works with nothing downloaded), and
  * an optional file of every US place with 5,000 or more people, made once by `python -m scripts.load_places`
    from GeoNames (https://www.geonames.org, licensed CC BY 4.0, see ATTRIBUTION.txt beside the file).
Nothing here sends anything anywhere.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.services.jobcache.text import fold

# (name, state, latitude, longitude)
BUILTIN: tuple[tuple[str, str, float, float], ...] = (
    ("Boston", "MA", 42.3601, -71.0589), ("Cambridge", "MA", 42.3736, -71.1097), ("Somerville", "MA", 42.3876, -71.0995),
    ("Quincy", "MA", 42.2529, -71.0023), ("Newton", "MA", 42.3370, -71.2092), ("Waltham", "MA", 42.3765, -71.2356),
    ("Brookline", "MA", 42.3318, -71.1212), ("Medford", "MA", 42.4184, -71.1062), ("Malden", "MA", 42.4251, -71.0662),
    ("Lynn", "MA", 42.4668, -70.9495), ("Braintree", "MA", 42.2079, -71.0017), ("Framingham", "MA", 42.2793, -71.4162),
    ("Burlington", "MA", 42.5048, -71.1956), ("Woburn", "MA", 42.4793, -71.1523), ("Lexington", "MA", 42.4473, -71.2245),
    ("Needham", "MA", 42.2809, -71.2379), ("Wellesley", "MA", 42.2968, -71.2924), ("Natick", "MA", 42.2834, -71.3495),
    ("Marlborough", "MA", 42.3459, -71.5523), ("Westborough", "MA", 42.2696, -71.6162), ("Worcester", "MA", 42.2626, -71.8023),
    ("Lowell", "MA", 42.6334, -71.3162), ("Andover", "MA", 42.6583, -71.1368), ("Chelmsford", "MA", 42.5998, -71.3673),
    ("Peabody", "MA", 42.5279, -70.9287), ("Salem", "MA", 42.5195, -70.8967), ("Springfield", "MA", 42.1015, -72.5898),
    ("Providence", "RI", 41.8240, -71.4128), ("Manchester", "NH", 42.9956, -71.4548), ("Nashua", "NH", 42.7654, -71.4676),
    ("Hartford", "CT", 41.7658, -72.6734), ("New Haven", "CT", 41.3083, -72.9279), ("Stamford", "CT", 41.0534, -73.5387),
    ("New York", "NY", 40.7128, -74.0060), ("Newark", "NJ", 40.7357, -74.1724), ("Jersey City", "NJ", 40.7178, -74.0431),
    ("Philadelphia", "PA", 39.9526, -75.1652), ("Pittsburgh", "PA", 40.4406, -79.9959), ("Baltimore", "MD", 39.2904, -76.6122),
    ("Washington", "DC", 38.9072, -77.0369), ("Arlington", "VA", 38.8816, -77.0910), ("Richmond", "VA", 37.5407, -77.4360),
    ("Raleigh", "NC", 35.7796, -78.6382), ("Durham", "NC", 35.9940, -78.8986), ("Charlotte", "NC", 35.2271, -80.8431),
    ("Atlanta", "GA", 33.7490, -84.3880), ("Orlando", "FL", 28.5383, -81.3792), ("Tampa", "FL", 27.9506, -82.4572),
    ("Miami", "FL", 25.7617, -80.1918), ("Jacksonville", "FL", 30.3322, -81.6557), ("Nashville", "TN", 36.1627, -86.7816),
    ("Memphis", "TN", 35.1495, -90.0490), ("Louisville", "KY", 38.2527, -85.7585), ("Cincinnati", "OH", 39.1031, -84.5120),
    ("Columbus", "OH", 39.9612, -82.9988), ("Cleveland", "OH", 41.4993, -81.6944), ("Detroit", "MI", 42.3314, -83.0458),
    ("Chicago", "IL", 41.8781, -87.6298), ("Indianapolis", "IN", 39.7684, -86.1581), ("Milwaukee", "WI", 43.0389, -87.9065),
    ("Minneapolis", "MN", 44.9778, -93.2650), ("St. Louis", "MO", 38.6270, -90.1994), ("Kansas City", "MO", 39.0997, -94.5786),
    ("Dallas", "TX", 32.7767, -96.7970), ("Houston", "TX", 29.7604, -95.3698), ("Austin", "TX", 30.2672, -97.7431),
    ("San Antonio", "TX", 29.4241, -98.4936), ("Denver", "CO", 39.7392, -104.9903), ("Phoenix", "AZ", 33.4484, -112.0740),
    ("Las Vegas", "NV", 36.1699, -115.1398), ("Salt Lake City", "UT", 40.7608, -111.8910), ("Seattle", "WA", 47.6062, -122.3321),
    ("Portland", "OR", 45.5152, -122.6784), ("San Francisco", "CA", 37.7749, -122.4194), ("San Jose", "CA", 37.3382, -121.8863),
    ("Oakland", "CA", 37.8044, -122.2712), ("Sacramento", "CA", 38.5816, -121.4944), ("Los Angeles", "CA", 34.0522, -118.2437),
    ("San Diego", "CA", 32.7157, -117.1611),
)

_ALIASES = ((r"^st ", "saint "), (r"^ft ", "fort "), (r"^mt ", "mount "))


def geo_file() -> Path:
    return Path(settings.JOB_CACHE_PATH).parent / "geo" / "us_places.json"


def key(city: str) -> str:
    out = fold(city)
    for pat, rep in _ALIASES:
        out = re.sub(pat, rep, out)
    return out


@lru_cache(maxsize=4)
def _table(path_str: str, mtime: float) -> dict[tuple[str, str], tuple[float, float, int, str]]:
    """(city key, state) -> (lat, lon, population). The built-in places first; the downloaded file adds to them and wins on a clash."""
    table: dict[tuple[str, str], tuple[float, float, int, str]] = {(key(n), s): (la, lo, 0, n) for n, s, la, lo in BUILTIN}
    path = Path(path_str)
    if mtime and path.exists():
        try:
            for name, state, la, lo, pop in json.loads(path.read_text(encoding="utf-8")):
                table[(key(name), state)] = (float(la), float(lo), int(pop), str(name))
        except (ValueError, OSError, TypeError):
            pass  # a damaged file: the built-in places still work
    return table


def table() -> dict[tuple[str, str], tuple[float, float, int, str]]:
    p = geo_file()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    return _table(str(p), mtime)


def lookup(city: str, state: str | None) -> tuple[float, float] | None:
    """Coordinates of a place. Without a state, the most populous place of that name."""
    k = key(city)
    t = table()
    if state:
        hit = t.get((k, state.upper()))
        return (hit[0], hit[1]) if hit else None
    best = max((v for (c, _s), v in t.items() if c == k), key=lambda v: v[2], default=None)
    return (best[0], best[1]) if best else None


def miles_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def nearby(city: str, state: str | None, radius: float = 25.0, limit: int = 25) -> list[str]:
    """
    "City, ST" for places within `radius` miles of a place (not the place itself), bigger places first, across state lines.
    Empty when the place has no known coordinates.
    """
    origin = lookup(city, state)
    if origin is None:
        return []
    own = key(city)
    found: list[tuple[int, float, str, str]] = []
    for (c, s), (la, lo, pop, shown) in table().items():
        if c == own and (not state or s == state.upper()):
            continue
        d = miles_between(origin, (la, lo))
        if d <= radius:
            found.append((pop, d, shown, s))
    found.sort(key=lambda r: (-r[0], r[1]))
    return [f"{shown}, {s}" for _pop, _d, shown, s in found[:limit]]
