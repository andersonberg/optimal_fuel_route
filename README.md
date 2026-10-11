# optimal_fuel_route

## Loading truck stop data

Run these in order from the project root (locally with `uv run python manage.py ...`, or in Docker with `docker compose run --rm web python manage.py ...`):

```sh
python manage.py migrate
python manage.py import_truckstops data/fuel-prices-for-be-assessment.csv
python manage.py import_places data/2026_Gaz_place_national.txt
python manage.py geocode_truckstops
```

### geocode_truckstops

Fills in `lat`/`lng` for truck stops that don't have coordinates yet.

1. Looks up each truck stop's city and state in the `Place` table (loaded by `import_places` from the Census gazetteer).
2. Cities not found there are geocoded with [OpenRouteService](https://openrouteservice.org/) and saved as new places.
3. Cities still not found are listed at the end of the output.

Set `ORS_API_KEY` to enable step 2; without it only Census places are used:

```sh
export ORS_API_KEY=your-key
python manage.py geocode_truckstops
```

With Docker Compose, `ORS_API_KEY` is passed through from your shell or a `.env` file next to `compose.yaml`.

Notes:

- Safe to re-run: only truck stops without coordinates are updated.
- Requests are throttled (~0.7s each) to stay inside the free ORS plan limit. If a request fails, progress is kept; re-run later to continue.
- Run `import_places` first so most cities resolve locally and few ORS requests are needed.

## Route API

`POST /api/route/` with `{"start": "Dallas, TX", "finish": "Chicago, IL"}` returns the driving route, the cheapest fuel stops along it and the total fuel cost. It needs `ORS_API_KEY` and the truck stop data loaded as above.

Note: this is a demo. The endpoint has no authentication or throttling, and every request uses OpenRouteService quota. Add both before exposing it publicly (see the TODO in `RouteView`).
