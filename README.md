# optimal_fuel_route

A Django API that takes a start and a finish inside the USA and returns the driving route, the cheapest fuel stops along it for a 500-mile range, and the total fuel cost at 10 MPG.

## Setup

Locally (needs [uv](https://docs.astral.sh/uv/)):

```sh
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Or with Docker:

```sh
docker compose up --build
```

Both serve on `http://localhost:8000`. The route endpoint needs an [OpenRouteService](https://openrouteservice.org/) key in `ORS_API_KEY`. Docker Compose passes it through from your shell or a `.env` file next to `compose.yaml`.

After adding a dependency, rebuild the container with `docker compose down -v && docker compose up --build`. The `-v` drops the cached virtualenv volume, which would otherwise keep the old packages.

Run the tests with `uv run python manage.py test optimal_fuel_route.calculate`. They mock every external call, so no key is needed.

## Data

Two files go in `data/`:

- `fuel-prices-for-be-assessment.csv`: the truck stop prices supplied with the assignment.
- `2026_Gaz_place_national.txt`: the free, public-domain Census gazetteer of US places. It gives every city a coordinate, so truck stops and the API's `"City, ST"` inputs are located without geocoding API calls.

```sh
curl -O https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_place_national.zip
unzip 2026_Gaz_place_national.zip -d data/
```

### Loading it

Run these in order from the project root (locally with `uv run python manage.py ...`, or in Docker with `docker compose run --rm web python manage.py ...`), once per database:

```sh
python manage.py migrate
python manage.py import_truckstops data/fuel-prices-for-be-assessment.csv
python manage.py import_places data/2026_Gaz_place_national.txt
python manage.py geocode_truckstops
```

`import_truckstops` adds rows every time it runs, so don't repeat it on a loaded database.

### geocode_truckstops

Fills in `lat`/`lng` for truck stops that don't have coordinates yet.

1. Looks up each truck stop's city and state in the `Place` table (loaded by `import_places` from the Census gazetteer).
2. Cities not found there are geocoded with OpenRouteService and saved as new places.
3. Cities still not found are listed at the end.

Set `ORS_API_KEY` to enable step 2; without it only Census places are used:

```sh
export ORS_API_KEY=your-key
python manage.py geocode_truckstops
```

Notes:

- Safe to re-run: only truck stops without coordinates are updated.
- Requests are throttled (~0.7s each) to stay inside the free ORS plan limit. If a request fails, progress is kept; re-run later to continue.
- Run `import_places` first so most cities resolve locally and few ORS requests are needed.
- Canadian stops are never geocoded and so never appear in routes.

## Route API

`POST /api/route/`

```json
{"start": "Dallas, TX", "finish": "Chicago, IL"}
```

Cities are `"City, ST"`, matched case-insensitively against the Census places. The response has this shape:

```json
{
  "distance_miles": 958.4,
  "total_gallons": 45.84,
  "total_cost": 133.2,
  "fuel_stops": [
    {"id": 123, "name": "...", "address": "...", "city": "...", "state": "MO",
     "lat": 38.78, "lng": -90.63, "mile": 538.6, "price": 2.904, "gallons": 41.98, "cost": 121.91}
  ],
  "map": {"type": "FeatureCollection", "features": ["route LineString", "one Point per fuel stop"]}
}
```

| Status | Meaning |
|---|---|
| 200 | Route and fuel plan returned |
| 400 | Missing field, wrong format, or a city not found |
| 422 | No fuel plan: a stretch of more than 500 miles has no truck stop |
| 502 | The routing service failed |

`map` is GeoJSON, so it can be pasted into any GeoJSON viewer. Each request makes at most one OpenRouteService call, and repeat trips are served from cache (see below).

### Map page

`GET /map/?start=Dallas, TX&finish=Chicago, IL` draws the same result on a Leaflet map: the route line plus a marker per fuel stop with its price, gallons and cost.

### Truck stops

`GET/POST /truckstops/` and `GET/PUT/PATCH/DELETE /truckstops/<id>/` manage the truck stop records.

### Postman

`optimal_fuel_route.postman_collection.json` has a request for each endpoint. Import it into Postman and set the `base_url` variable if you aren't on `localhost:8000`.

## How the plan is chosen

- The vehicle starts with a full 500-mile tank that costs nothing, and ends the trip empty. Only fuel bought at stations is counted.
- Fuel consumption is 10 miles per gallon.
- Truck stops within 10 miles of the route are candidates. Stop coordinates are city-level, so the tolerance is generous, and a stop's detour off the route is not counted.
- The planner is greedy: at each stop it buys just enough to reach the next cheaper stop, or fills up when nothing cheaper is in range and drives to the cheapest stop it can reach. This matches the fixed-path algorithm from Khuller, Malekian and Mestre, "To Fill or not to Fill: The Gas Station Problem".
- This can produce small top-up purchases near the start. They are cost-optimal.

## Performance and caching

The directions from OpenRouteService are the slow, quota-limited part, so they are cached by start and finish for 24 hours using Django's default in-memory cache. A repeat of the same trip makes no external call. The cache is per process and is emptied on restart; for several workers, configure a shared cache backend in `CACHES`.

With the routing call mocked, building a Dallas-to-Chicago response from the real database takes about 80 ms. Measure the live difference with a key:

```sh
curl -s -o /dev/null -w '%{time_total}s\n' -X POST localhost:8000/api/route/ \
  -H 'Content-Type: application/json' -d '{"start": "Dallas, TX", "finish": "Chicago, IL"}'
```

Run it twice. The second call should be noticeably faster.

## Demo limits

This is a demo. The endpoints have no authentication or throttling, and every uncached route request uses OpenRouteService quota. Add both before exposing it publicly (see the TODO in `RouteView`). The map page loads Leaflet from unpkg and tiles from OpenStreetMap, which is fine for a demo and not for heavy use.
