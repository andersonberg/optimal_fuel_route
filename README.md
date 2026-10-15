# optimal_fuel_route

A Django API that takes a start and a finish inside the USA and returns the driving route, the cheapest fuel stops along it for a 500-mile range, and the total fuel cost at 10 MPG.  
  
**Disclaimer**: Most of the code was AI generated. I used spec-driven development taking some rounds to get a final approval of the code. I based my algorithm in a paper I found in the internet [https://www.cs.umd.edu/projects/gas/gas-station.pdf](https://www.cs.umd.edu/projects/gas/gas-station.pdf), especially the fixed-path gas station problem at Apendix B. 

## Setup from scratch (Docker)

The database (`db.sqlite3`) and the `data/` folder are not in the repository, so a fresh clone starts with no truck stops, no US places and no coordinates. Follow these steps in order.

You need [Docker](https://docs.docker.com/get-docker/) with Compose, `curl` and `unzip`. A free [OpenRouteService](https://openrouteservice.org/) key is needed for the route endpoint (and recommended for geocoding).

**1. Clone and add your OpenRouteService key.**

```sh
git clone <repository-url> optimal_fuel_route
cd optimal_fuel_route
echo 'ORS_API_KEY=your-key' > .env
```

Docker Compose reads `.env` automatically and passes the key into the container.

**2. Put the data files in** `data/`**.**

```sh
mkdir -p data
```

- Copy `fuel-prices-for-be-assessment.csv` (the truck stop prices supplied with the assignment) into `data/`. It is not in the repository.
- Download the free, public-domain Census gazetteer of US places:

```sh
curl -o data/places.zip https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_place_national.zip
unzip data/places.zip -d data/
```

You should now have `data/fuel-prices-for-be-assessment.csv` and `data/2026_Gaz_place_national.txt`.

**3. Build the image and create the database.**

```sh
docker compose build
docker compose run --rm web python manage.py migrate
```

The project folder is mounted into the container, so `db.sqlite3` is created in your project folder and survives restarts.

**4. Load the data, in this order.**

```sh
docker compose run --rm web python manage.py import_truckstops data/fuel-prices-for-be-assessment.csv
docker compose run --rm web python manage.py import_places data/2026_Gaz_place_national.txt
docker compose run --rm web python manage.py geocode_truckstops
```

What to expect with the supplied CSV:


| Command              | Output                                                                              |
| -------------------- | ----------------------------------------------------------------------------------- |
| `import_truckstops`  | `Imported 8151 truck stops.`                                                        |
| `import_places`      | `Imported 32130 places.`                                                            |
| `geocode_truckstops` | `Geocoded N truck stops.` and, at the end, a list of cities that could not be found |


The Census places alone give coordinates to about 88% of the stops (7,146 of 8,151). With `ORS_API_KEY` set, `geocode_truckstops` also looks up the remaining US cities, which takes a few minutes because requests are throttled to ~0.7 s each. Canadian stops are never geocoded, so a short list of not-found cities is normal. See [geocode_truckstops](#geocode_truckstops).

**5. Start the API.**

```sh
docker compose up
```

It serves on `http://localhost:8000`. Check it:

```sh
curl -s http://localhost:8000/truckstops/1/
curl -s -X POST http://localhost:8000/api/route/ -H 'Content-Type: application/json' \
  -d '{"start": "Dallas, TX", "finish": "Chicago, IL"}'
```

The first returns a truck stop with `lat` and `lng` filled in. The second returns the route, fuel stops and cost, and needs the key from step 1. You can also open `http://localhost:8000/map/?start=Dallas, TX&finish=Chicago, IL`.

### Everyday commands

- **Run the tests:** `docker compose run --rm web python manage.py test optimal_fuel_route.calculate`. They mock every external call, so no key is needed.
- **After adding a dependency:** `docker compose down -v && docker compose up --build`. The `-v` drops the cached virtualenv volume, which would otherwise keep the old packages.
- **Start the data over:** stop the app, delete `db.sqlite3`, then repeat steps 3 and 4. Don't re-run `import_truckstops` on a loaded database: it adds the rows again.



## Setup without Docker (uv)

Needs [uv](https://docs.astral.sh/uv/), which installs the Python version in `.python-version` for you. Do steps 1 and 2 above (put the key in your environment instead of `.env`: `export ORS_API_KEY=your-key`), then:

```sh
uv sync
uv run python manage.py migrate
uv run python manage.py import_truckstops data/fuel-prices-for-be-assessment.csv
uv run python manage.py import_places data/2026_Gaz_place_national.txt
uv run python manage.py geocode_truckstops
uv run python manage.py runserver
```

Run the tests with `uv run python manage.py test optimal_fuel_route.calculate`.

## Data

- `fuel-prices-for-be-assessment.csv`: truck stop names, addresses, cities, states and retail prices.
- `2026_Gaz_place_national.txt`: every US place with a coordinate. It lets truck stops and the API's `"City, ST"` inputs be located without geocoding API calls. Only the few cities it lacks need OpenRouteService.

Both live in `data/`, which is git-ignored.

### geocode_truckstops

Fills in `lat`/`lng` for truck stops that don't have coordinates yet.

1. Looks up each truck stop's city and state in the `Place` table (loaded by `import_places` from the Census gazetteer).
2. Cities not found there are geocoded with OpenRouteService and saved as new places.
3. Cities still not found are listed at the end.

Without `ORS_API_KEY`, only step 1 runs and a warning is printed.

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


| Status | Meaning                                                          |
| ------ | ---------------------------------------------------------------- |
| 200    | Route and fuel plan returned                                     |
| 400    | Missing field, wrong format, or a city not found                 |
| 422    | No fuel plan: a stretch of more than 500 miles has no truck stop |
| 502    | The routing service failed                                       |


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