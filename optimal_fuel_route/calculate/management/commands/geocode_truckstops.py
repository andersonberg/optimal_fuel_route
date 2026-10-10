import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from optimal_fuel_route.calculate.locations import US_STATES, geocode_city, normalize_city
from optimal_fuel_route.calculate.models import Place, TruckStop

# Free OpenRouteService plan allows ~100 requests per minute.
ORS_DELAY_SECONDS = 0.7


class Command(BaseCommand):
    help = (
        'Fill in truck stop coordinates from the Place table (Census data). '
        'Cities missing there are geocoded with OpenRouteService and saved as new places. '
        'Only truck stops without coordinates are touched, so it is safe to re-run.'
    )

    def handle(self, *args, **options):
        if not settings.ORS_API_KEY:
            self.stdout.write(self.style.WARNING('ORS_API_KEY is not set: only Census places will be used.'))

        cities = TruckStop.objects.filter(lat__isnull=True).values_list('city', 'state').distinct()
        updated = 0
        not_found = []

        for city, state in cities:
            key = normalize_city(city)
            place = Place.objects.filter(state=state, key=key).first()

            if place is None and settings.ORS_API_KEY and state in US_STATES:
                time.sleep(ORS_DELAY_SECONDS)
                try:
                    coords = geocode_city(city, state)
                except requests.RequestException as e:
                    # Not str(e): requests puts the full URL in the message.
                    raise CommandError(
                        f'OpenRouteService request failed ({type(e).__name__}). Progress is saved; re-run later.'
                    )
                if coords:
                    place = Place.objects.create(state=state, key=key, lat=coords[0], lng=coords[1])

            if place is None:
                not_found.append(f'{city}, {state}')
                continue

            updated += TruckStop.objects.filter(city=city, state=state, lat__isnull=True).update(
                lat=place.lat, lng=place.lng,
            )

        self.stdout.write(self.style.SUCCESS(f'Geocoded {updated} truck stops.'))
        if not_found:
            self.stdout.write(f'{len(not_found)} cities not found: {"; ".join(not_found)}')
