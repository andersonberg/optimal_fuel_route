import re

import requests
from django.conf import settings

US_STATES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS',
    'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC',
    'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
}

ORS_GEOCODE_URL = 'https://api.openrouteservice.org/geocode/search/structured'

# Result types precise enough to stand for a town. Coarser ones (county, state) are rejected.
CITY_LAYERS = {'locality', 'localadmin', 'borough', 'neighbourhood'}


def normalize_city(name):
    """Turn a city name into a lookup key, e.g. 'St. Louis' and 'Saint Louis' -> 'saintlouis'."""
    name = re.sub(r'\bst\b', 'saint', name.lower())
    return re.sub(r'[^a-z0-9]', '', name)


def geocode_city(city, state):
    """Ask OpenRouteService for a US city's (lat, lng). Returns None if it can't find the city itself."""
    response = requests.get(
        ORS_GEOCODE_URL,
        headers={'Authorization': settings.ORS_API_KEY},
        params={
            'locality': city,
            'region': state,
            'country': 'USA',
            'size': 1,
        },
        timeout=10,
    )
    response.raise_for_status()

    features = response.json()['features']
    if not features:
        return None

    feature = features[0]
    if feature['properties'].get('layer') not in CITY_LAYERS:
        return None
    if feature['properties'].get('region_a') != state:
        return None
    if normalize_city(feature['properties'].get('name', '')) != normalize_city(city):
        return None

    lng, lat = feature['geometry']['coordinates']
    return lat, lng
