import io
import tempfile

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from optimal_fuel_route.calculate.locations import normalize_city
from optimal_fuel_route.calculate.management.commands.import_places import strip_census_suffix
from optimal_fuel_route.calculate.models import Place


class NormalizeCityTests(SimpleTestCase):
    def test_lowercases_and_removes_spaces_and_punctuation(self):
        self.assertEqual(normalize_city('Big Cabin'), 'bigcabin')
        self.assertEqual(normalize_city('Mc Calla'), normalize_city('McCalla'))

    def test_saint_and_st_match(self):
        self.assertEqual(normalize_city('St. Louis'), 'saintlouis')
        self.assertEqual(normalize_city('Saint Louis'), 'saintlouis')
        self.assertEqual(normalize_city('East St Louis'), 'eastsaintlouis')

    def test_st_inside_a_word_is_kept(self):
        self.assertEqual(normalize_city('Stanton'), 'stanton')


class StripCensusSuffixTests(SimpleTestCase):
    def test_strips_trailing_census_words(self):
        self.assertEqual(strip_census_suffix('Big Cabin town'), 'Big Cabin')
        self.assertEqual(strip_census_suffix('McCalla CDP'), 'McCalla')
        self.assertEqual(
            strip_census_suffix('Nashville-Davidson metropolitan government (balance)'),
            'Nashville-Davidson',
        )


class ImportPlacesTests(TestCase):
    SAMPLE = (
        'USPS|GEOID|NAME|INTPTLAT|INTPTLONG\n'
        'OK|4005900|Big Cabin town|36.537602|-95.229368          \n'
        'MO|2965000|St. Louis city|38.635699|-90.244582\n'
        'MI|2671000|St. Louis city|43.408528|-84.61123\n'
    )

    def import_sample(self):
        with tempfile.NamedTemporaryFile('w', suffix='.txt') as f:
            f.write(self.SAMPLE)
            f.flush()
            call_command('import_places', f.name, stdout=io.StringIO())

    def test_imports_places_with_normalized_keys(self):
        self.import_sample()

        place = Place.objects.get(state='OK', key='bigcabin')
        self.assertEqual((place.lat, place.lng), (36.537602, -95.229368))
        self.assertTrue(Place.objects.filter(state='MO', key='saintlouis').exists())
        self.assertTrue(Place.objects.filter(state='MI', key='saintlouis').exists())

    def test_running_twice_does_not_duplicate(self):
        self.import_sample()
        self.import_sample()

        self.assertEqual(Place.objects.count(), 3)
