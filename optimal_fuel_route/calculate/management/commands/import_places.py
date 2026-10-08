import csv
import re

from django.core.management.base import BaseCommand

from optimal_fuel_route.calculate.locations import normalize_city
from optimal_fuel_route.calculate.models import Place


def strip_census_suffix(name):
    """'Big Cabin town' -> 'Big Cabin'. Census names end with lowercase words like 'city' or 'CDP'."""
    return re.sub(r'(\s+([a-z]+|CDP|\(balance\)))+$', '', name)


class Command(BaseCommand):
    help = 'Import US places from the Census gazetteer places file (pipe-delimited).'

    def add_arguments(self, parser):
        parser.add_argument('path')

    def handle(self, *args, **options):
        with open(options['path'], newline='', encoding='utf-8') as f:
            places = [
                Place(
                    state=row['USPS'],
                    key=normalize_city(strip_census_suffix(row['NAME'])),
                    lat=float(row['INTPTLAT']),
                    lng=float(row['INTPTLONG'].strip()),
                )
                for row in csv.DictReader(f, delimiter='|')
            ]

        Place.objects.bulk_create(places, ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS(f'Imported {Place.objects.count()} places.'))
