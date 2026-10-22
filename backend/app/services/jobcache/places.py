"""
City suggestions for the search box: type "Bost" and "Boston, MA" is offered. The list is a built-in set of larger US
cities (largest first, so "San" offers the big ones first) plus every city the saved job lists mention, so a smaller
town that has openings can be picked too. Nothing is sent anywhere; this is plain text matching.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.services.jobcache.text import US_STATES, fold

# "City ST" entries, roughly largest first.
_BUILTIN = """
New York NY;Los Angeles CA;Chicago IL;Houston TX;Phoenix AZ;Philadelphia PA;San Antonio TX;San Diego CA;Dallas TX;Jacksonville FL;
Fort Worth TX;San Jose CA;Austin TX;Charlotte NC;Columbus OH;Indianapolis IN;San Francisco CA;Seattle WA;Denver CO;Washington DC;
Oklahoma City OK;Nashville TN;El Paso TX;Boston MA;Las Vegas NV;Portland OR;Detroit MI;Louisville KY;Memphis TN;Baltimore MD;
Milwaukee WI;Albuquerque NM;Tucson AZ;Fresno CA;Sacramento CA;Mesa AZ;Atlanta GA;Kansas City MO;Colorado Springs CO;Omaha NE;
Raleigh NC;Miami FL;Virginia Beach VA;Long Beach CA;Oakland CA;Minneapolis MN;Bakersfield CA;Tulsa OK;Tampa FL;Arlington TX;
Wichita KS;Aurora CO;New Orleans LA;Cleveland OH;Honolulu HI;Anaheim CA;Henderson NV;Orlando FL;Lexington KY;Stockton CA;
Riverside CA;Irvine CA;Corpus Christi TX;Newark NJ;Santa Ana CA;Cincinnati OH;Pittsburgh PA;Saint Paul MN;Greensboro NC;Jersey City NJ;
Durham NC;Lincoln NE;North Las Vegas NV;Plano TX;Anchorage AK;Gilbert AZ;Madison WI;Reno NV;Chandler AZ;St. Louis MO;
Chula Vista CA;Buffalo NY;Fort Wayne IN;Lubbock TX;St. Petersburg FL;Toledo OH;Laredo TX;Port St. Lucie FL;Glendale AZ;Irving TX;
Winston-Salem NC;Chesapeake VA;Garland TX;Scottsdale AZ;Norfolk VA;Boise ID;Fremont CA;Spokane WA;Santa Clarita CA;Baton Rouge LA;
Richmond VA;Hialeah FL;San Bernardino CA;Tacoma WA;Modesto CA;Huntsville AL;Des Moines IA;Yonkers NY;Rochester NY;Moreno Valley CA;
Fayetteville NC;Fontana CA;Columbus GA;Worcester MA;Port Orchard WA;Little Rock AR;Augusta GA;Oxnard CA;Birmingham AL;Montgomery AL;
Frisco TX;Amarillo TX;Salt Lake City UT;Grand Rapids MI;Huntington Beach CA;Overland Park KS;Glendale CA;Tallahassee FL;Grand Prairie TX;McKinney TX;
Cape Coral FL;Sioux Falls SD;Peoria AZ;Providence RI;Vancouver WA;Knoxville TN;Akron OH;Shreveport LA;Mobile AL;Brownsville TX;
Newport News VA;Fort Lauderdale FL;Chattanooga TN;Tempe AZ;Aurora IL;Santa Rosa CA;Eugene OR;Elk Grove CA;Salem OR;Cary NC;
Fort Collins CO;Springfield MO;Jackson MS;Alexandria VA;Hayward CA;Lancaster CA;Lakewood CO;Clarksville TN;Palmdale CA;Salinas CA;
Hollywood FL;Springfield MA;Macon GA;Kansas City KS;Sunnyvale CA;Pomona CA;Killeen TX;Escondido CA;Pasadena TX;Naperville IL;
Bellevue WA;Joliet IL;Murfreesboro TN;Midland TX;Rockford IL;Paterson NJ;Savannah GA;Bridgeport CT;Torrance CA;McAllen TX;
Syracuse NY;Surprise AZ;Denton TX;Roseville CA;Thornton CO;Miramar FL;Mesquite TX;Olathe KS;Dayton OH;Carrollton TX;
Waco TX;Orange CA;Fullerton CA;Charleston SC;West Valley City UT;Visalia CA;Hampton VA;Gainesville FL;Warren MI;Coral Springs FL;
Cedar Rapids IA;Round Rock TX;Sterling Heights MI;Kent WA;Columbia SC;Santa Clara CA;New Haven CT;Stamford CT;Concord CA;Elizabeth NJ;
Athens GA;Thousand Oaks CA;Lafayette LA;Simi Valley CA;Topeka KS;Norman OK;Fargo ND;Wilmington NC;Abilene TX;Odessa TX;
Pearland TX;Victorville CA;Hartford CT;Vallejo CA;Allentown PA;Berkeley CA;Richardson TX;Arvada CO;Ann Arbor MI;Cambridge MA;
Sugar Land TX;Lansing MI;Evansville IN;College Station TX;Fairfield CA;Clearwater FL;Beaumont TX;Independence MO;Provo UT;West Jordan UT;
Murrieta CA;Palm Bay FL;El Monte CA;Carlsbad CA;Charleston WV;Temecula CA;Clovis CA;Springfield IL;Meridian ID;Westminster CO;
Costa Mesa CA;High Point NC;Manchester NH;Pueblo CO;Lakeland FL;Pompano Beach FL;West Palm Beach FL;Antioch CA;Everett WA;Downey CA;
Lowell MA;Centennial CO;Elgin IL;Broken Arrow OK;Miami Gardens FL;Billings MT;Jurupa Valley CA;Sandy Springs GA;Gresham OR;Lewisville TX;
Hillsboro OR;Ventura CA;Greeley CO;Inglewood CA;Waterbury CT;League City TX;Santa Maria CA;Tyler TX;Davie FL;Daly City CA;
Boulder CO;Allen TX;West Covina CA;Sparks NV;Wichita Falls TX;Green Bay WI;San Mateo CA;Norwalk CA;Rialto CA;Las Cruces NM;
Chico CA;El Cajon CA;Burbank CA;South Bend IN;Renton WA;Vista CA;Davenport IA;Edinburg TX;Tuscaloosa AL;Carmel IN;
Spokane Valley WA;San Angelo TX;Vacaville CA;Bend OR;Woodbridge NJ;Brockton MA;Quincy MA;Newton MA;Somerville MA;Waltham MA;
Burlington MA;Framingham MA;Lexington MA;Woburn MA;Andover MA;Marlborough MA;Braintree MA;Needham MA;Chelmsford MA;Westborough MA;
Portland ME;Burlington VT;Concord NH;Nashua NH;Portsmouth NH;Princeton NJ;Parsippany NJ;White Plains NY;Albany NY;Ithaca NY;
Rockville MD;Bethesda MD;Silver Spring MD;Columbia MD;Reston VA;McLean VA;Tysons VA;Arlington VA;Fairfax VA;Durham NC;
Research Triangle Park NC;Chapel Hill NC;Greenville SC;Nashville TN;Franklin TN;Brentwood TN;Winter Park FL;Lake Mary FL;Kissimmee FL;Sanford FL;
Altamonte Springs FL;Maitland FL;Celebration FL;Boca Raton FL;Palo Alto CA;Mountain View CA;Menlo Park CA;Redwood City CA;South San Francisco CA;San Ramon CA;
Pleasanton CA;Walnut Creek CA;Emeryville CA;Culver City CA;Santa Monica CA;Pasadena CA;Rancho Cordova CA;Folsom CA;Redmond WA;Kirkland WA;
Scottsdale AZ;Eden Prairie MN;Rochester MN;Plymouth MN;Bloomington MN;Southfield MI;Troy MI;Dearborn MI;Dublin OH;Westlake OH;
Lake Forest IL;Schaumburg IL;Oak Brook IL;Deerfield IL;Northbrook IL;Overland Park KS;Lenexa KS;Irving TX;Addison TX;Southlake TX
"""


_US_WORDS = ("united states", "usa", "america", "american")


@lru_cache(maxsize=1)
def builtin() -> tuple[tuple[str, str], ...]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for chunk in re.split(r";", _BUILTIN.replace("\n", "")):
        chunk = chunk.strip()
        if not chunk:
            continue
        city, _, state = chunk.rpartition(" ")
        if state not in US_STATES or not city:
            continue
        key = (fold(city), state)
        if key not in seen:
            seen.add(key)
            out.append((city, state))
    return tuple(out)


def _from_postings(locations: list[str]) -> list[tuple[str, str]]:
    """"City, ST" places named by saved postings (most often named first), for towns the built-in list does not have."""
    counts: dict[tuple[str, str], int] = {}
    for loc in locations:
        m = re.match(r"^\s*([A-Za-z][A-Za-z .'\-]{2,40}?)\s*,\s*([A-Z]{2})\b", loc or "")
        if m and m.group(2) in US_STATES:
            key = (m.group(1).strip(), m.group(2))
            counts[key] = counts.get(key, 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def suggest(query: str, extra_locations: list[str] | None = None, limit: int = 8) -> list[dict[str, str]]:
    """Places that start with what was typed ("bost" -> Boston, MA), larger cities first, then places only the job lists mention."""
    q = fold(query)
    if len(q) < 2:
        return []
    # "bos, ma" or "boston ma": the part after a comma (or a trailing state) narrows by state.
    state: str | None = None
    m = re.match(r"^(.*?)[,\s]+([a-z]{2})$", q)
    if m and m.group(2).upper() in US_STATES and len(m.group(1)) >= 2:
        q, state = m.group(1).strip(), m.group(2).upper()
    out: list[dict[str, str]] = []
    if any(w.startswith(q) for w in _US_WORDS):  # "un", "unit", "us", "usa", "ame": offer the whole country first
        out.append({"label": "United States", "city": "", "state": ""})
    seen: set[tuple[str, str]] = set()
    pools = [list(builtin()), _from_postings(extra_locations or [])]
    for pool in pools:
        for city, st in pool:
            key = (fold(city), st)
            if key in seen or (state and st != state):
                continue
            name = fold(city)
            if name.startswith(q) or any(w.startswith(q) for w in name.split()[1:] if len(q) >= 3):
                seen.add(key)
                out.append({"label": f"{city}, {st}", "city": city, "state": st})
            if len(out) >= limit:
                return out
    if "remote".startswith(q) and len(out) < limit:
        out.append({"label": "Remote", "city": "Remote", "state": ""})
    return out
