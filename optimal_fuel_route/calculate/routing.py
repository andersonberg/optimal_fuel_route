import requests
from django.conf import settings

ORS_DIRECTIONS_URL = 'https://api.openrouteservice.org/v2/directions/driving-car/geojson'


def get_route(start, finish):
    """Drive from start to finish, each a (lat, lng) pair.

    Returns (coords, distance_miles), where coords is a list of (lat, lng) points along the road.
    """
    response = requests.post(
        ORS_DIRECTIONS_URL,
        headers={'Authorization': settings.ORS_API_KEY},
        json={
            # ORS wants [lng, lat].
            'coordinates': [[start[1], start[0]], [finish[1], finish[0]]],
            'units': 'mi',
        },
        timeout=30,
    )
    response.raise_for_status()

    feature = response.json()['features'][0]
    coords = [(lat, lng) for lng, lat in feature['geometry']['coordinates']]
    return coords, feature['properties']['summary']['distance']
