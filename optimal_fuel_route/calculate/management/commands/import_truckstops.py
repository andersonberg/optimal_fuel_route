import csv

from django.core.management.base import BaseCommand

from optimal_fuel_route.calculate.models import TruckStop


class Command(BaseCommand):
    help = 'Import truck stops from a fuel prices CSV file.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path')

    def handle(self, *args, **options):
        with open(options['csv_path'], newline='', encoding='utf-8') as f:
            truckstops = [
                TruckStop(
                    opis_id=int(row['OPIS Truckstop ID']),
                    name=row['Truckstop Name'].strip(),
                    address=row['Address'].strip(),
                    city=row['City'].strip(),
                    state=row['State'].strip(),
                    rack_id=int(row['Rack ID']),
                    retail_price=row['Retail Price'],
                )
                for row in csv.DictReader(f)
            ]

        TruckStop.objects.bulk_create(truckstops)
        self.stdout.write(self.style.SUCCESS(f'Imported {len(truckstops)} truck stops.'))
