import numpy as np

from optimal_fuel_route.calculate.models import TruckStop

EARTH_RADIUS_MILES = 3958.8
MILES_PER_DEGREE_LAT = 69.0

# Stops are compared to the route in batches so the distance matrix stays small.
CHUNK_SIZE = 100


def haversine_miles(lat1, lng1, lat2, lng2):
    """Great-circle distance in miles. Works on numbers or numpy arrays."""
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def find_stops_along_route(coords, tolerance_miles=10):
    """Truck stops within tolerance_miles of the route, as (stop, mile_marker, price) sorted by mile marker.

    coords is the route as (lat, lng) points. Stop coordinates are city-level, hence the generous tolerance.
    """
    route = np.array(coords, dtype=float)
    lats, lngs = route[:, 0], route[:, 1]

    steps = haversine_miles(lats[:-1], lngs[:-1], lats[1:], lngs[1:])
    miles = np.concatenate(([0.0], np.cumsum(steps)))

    # Bounding box prefilter, so the database only returns stops that could be near the route.
    pad_lat = tolerance_miles / MILES_PER_DEGREE_LAT
    pad_lng = tolerance_miles / (MILES_PER_DEGREE_LAT * np.cos(np.radians(np.abs(lats).max())))
    candidates = list(TruckStop.objects.filter(
        lat__gte=lats.min() - pad_lat, lat__lte=lats.max() + pad_lat,
        lng__gte=lngs.min() - pad_lng, lng__lte=lngs.max() + pad_lng,
    ))

    found = []
    for start in range(0, len(candidates), CHUNK_SIZE):
        chunk = candidates[start:start + CHUNK_SIZE]
        stop_lats = np.array([s.lat for s in chunk])[:, None]
        stop_lngs = np.array([s.lng for s in chunk])[:, None]

        distances = haversine_miles(stop_lats, stop_lngs, lats[None, :], lngs[None, :])
        nearest = distances.argmin(axis=1)
        nearest_distance = distances[np.arange(len(chunk)), nearest]

        for stop, point, distance in zip(chunk, nearest, nearest_distance):
            if distance <= tolerance_miles:
                found.append((stop, float(miles[point]), float(stop.retail_price)))

    found.sort(key=lambda row: row[1])
    return found
