import io
import tempfile
from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings

from optimal_fuel_route.calculate.fuel import FuelPlanError, plan_fuel_stops
from optimal_fuel_route.calculate.locations import geocode_city, normalize_city
from optimal_fuel_route.calculate.management.commands.import_places import strip_census_suffix
from optimal_fuel_route.calculate.models import Place, TruckStop
from optimal_fuel_route.calculate.routing import get_route
from optimal_fuel_route.calculate.stations import find_stops_along_route, haversine_miles


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


def ors_response(layer='locality', region_a='TX', name='Pecos', coordinates=(-103.49, 31.42)):
    """A minimal OpenRouteService geocode response with one feature."""
    response = Mock()
    response.json.return_value = {
        'features': [{
            'geometry': {'coordinates': list(coordinates)},
            'properties': {'layer': layer, 'region_a': region_a, 'name': name},
        }],
    }
    return response


@patch('optimal_fuel_route.calculate.locations.requests.get')
class GeocodeCityTests(SimpleTestCase):
    def test_returns_lat_lng(self, mock_get):
        mock_get.return_value = ors_response()

        self.assertEqual(geocode_city('Pecos', 'TX'), (31.42, -103.49))

    def test_returns_none_when_nothing_found(self, mock_get):
        mock_get.return_value.json.return_value = {'features': []}

        self.assertIsNone(geocode_city('Nowhere', 'TX'))

    def test_rejects_results_coarser_than_a_city(self, mock_get):
        mock_get.return_value = ors_response(layer='region')

        self.assertIsNone(geocode_city('Pecos', 'TX'))

    def test_rejects_results_in_another_state(self, mock_get):
        mock_get.return_value = ors_response(region_a='NM')

        self.assertIsNone(geocode_city('Pecos', 'TX'))

    def test_rejects_results_for_a_different_city(self, mock_get):
        mock_get.return_value = ors_response(name='Odessa')

        self.assertIsNone(geocode_city('Pecos', 'TX'))

    @override_settings(ORS_API_KEY='secret-key')
    def test_sends_key_in_header_not_url(self, mock_get):
        mock_get.return_value = ors_response()

        geocode_city('Pecos', 'TX')

        kwargs = mock_get.call_args.kwargs
        self.assertEqual(kwargs['headers'], {'Authorization': 'secret-key'})
        self.assertNotIn('api_key', kwargs['params'])

    def test_raises_on_http_error(self, mock_get):
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError('429 Too Many Requests')

        with self.assertRaises(requests.HTTPError):
            geocode_city('Pecos', 'TX')


@override_settings(ORS_API_KEY='test-key')
@patch('optimal_fuel_route.calculate.management.commands.geocode_truckstops.time.sleep')
@patch('optimal_fuel_route.calculate.management.commands.geocode_truckstops.geocode_city')
class GeocodeTruckstopsTests(TestCase):
    def create_stop(self, city, state, **kwargs):
        return TruckStop.objects.create(
            opis_id=1, name='STOP', address='I-1', city=city, state=state,
            rack_id=1, retail_price='3.5', **kwargs,
        )

    def run_command(self):
        call_command('geocode_truckstops', stdout=io.StringIO())

    def test_uses_census_place_without_calling_ors(self, mock_geocode, mock_sleep):
        Place.objects.create(state='OK', key='bigcabin', lat=36.54, lng=-95.23)
        stops = [self.create_stop('Big Cabin', 'OK'), self.create_stop('Big Cabin', 'OK')]

        self.run_command()

        mock_geocode.assert_not_called()
        for stop in stops:
            stop.refresh_from_db()
            self.assertEqual((stop.lat, stop.lng), (36.54, -95.23))

    def test_geocodes_missing_city_with_ors_and_saves_place(self, mock_geocode, mock_sleep):
        mock_geocode.return_value = (31.42, -103.49)
        stop = self.create_stop('Pecos', 'TX')

        self.run_command()

        mock_geocode.assert_called_once_with('Pecos', 'TX')
        self.assertTrue(Place.objects.filter(state='TX', key='pecos').exists())
        stop.refresh_from_db()
        self.assertEqual((stop.lat, stop.lng), (31.42, -103.49))

    def test_does_not_touch_stops_that_already_have_coordinates(self, mock_geocode, mock_sleep):
        stop = self.create_stop('Pecos', 'TX', lat=1.0, lng=2.0)

        self.run_command()

        mock_geocode.assert_not_called()
        stop.refresh_from_db()
        self.assertEqual((stop.lat, stop.lng), (1.0, 2.0))

    def test_second_run_makes_no_ors_calls(self, mock_geocode, mock_sleep):
        mock_geocode.return_value = (31.42, -103.49)
        self.create_stop('Pecos', 'TX')

        self.run_command()
        self.run_command()

        self.assertEqual(mock_geocode.call_count, 1)

    def test_city_not_found_stays_empty(self, mock_geocode, mock_sleep):
        mock_geocode.return_value = None
        stop = self.create_stop('Nowhere', 'TX')

        self.run_command()

        stop.refresh_from_db()
        self.assertIsNone(stop.lat)

    def test_skips_ors_for_non_us_states(self, mock_geocode, mock_sleep):
        self.create_stop('Edmonton', 'AB')

        self.run_command()

        mock_geocode.assert_not_called()

    @override_settings(ORS_API_KEY='')
    def test_skips_ors_without_api_key(self, mock_geocode, mock_sleep):
        self.create_stop('Pecos', 'TX')

        self.run_command()

        mock_geocode.assert_not_called()

    def test_ors_error_stops_with_command_error(self, mock_geocode, mock_sleep):
        mock_geocode.side_effect = requests.HTTPError('429 for url: https://x/?api_key=test-key')
        self.create_stop('Pecos', 'TX')

        with self.assertRaises(CommandError) as ctx:
            self.run_command()
        self.assertNotIn('test-key', str(ctx.exception))


@patch('optimal_fuel_route.calculate.routing.requests.post')
class GetRouteTests(SimpleTestCase):
    DALLAS = (32.78, -96.80)
    CHICAGO = (41.88, -87.63)

    def directions(self):
        response = Mock()
        response.json.return_value = {
            'features': [{
                'geometry': {'coordinates': [[-96.80, 32.78], [-92.0, 37.0], [-87.63, 41.88]]},
                'properties': {'summary': {'distance': 967.5}},
            }]
        }
        return response

    def test_returns_lat_lng_points_and_miles(self, mock_post):
        mock_post.return_value = self.directions()

        coords, miles = get_route(self.DALLAS, self.CHICAGO)

        self.assertEqual(coords, [(32.78, -96.80), (37.0, -92.0), (41.88, -87.63)])
        self.assertEqual(miles, 967.5)

    def test_sends_lng_lat_pairs_in_miles(self, mock_post):
        mock_post.return_value = self.directions()

        get_route(self.DALLAS, self.CHICAGO)

        body = mock_post.call_args.kwargs['json']
        self.assertEqual(body['coordinates'], [[-96.80, 32.78], [-87.63, 41.88]])
        self.assertEqual(body['units'], 'mi')

    @override_settings(ORS_API_KEY='secret-key')
    def test_sends_key_in_header_not_url(self, mock_post):
        mock_post.return_value = self.directions()

        get_route(self.DALLAS, self.CHICAGO)

        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs['headers'], {'Authorization': 'secret-key'})
        self.assertNotIn('secret-key', mock_post.call_args.args[0])

    def test_raises_on_http_error(self, mock_post):
        mock_post.return_value.raise_for_status.side_effect = requests.HTTPError('404 Not Found')

        with self.assertRaises(requests.HTTPError):
            get_route(self.DALLAS, self.CHICAGO)


class FindStopsAlongRouteTests(TestCase):
    # A straight east-west route at 35N from 100W to 90W, a point every 0.1 degree.
    ROUTE = [(35.0, -100.0 + i / 10) for i in range(101)]

    def make_stop(self, name, lat, lng, price='3.50'):
        return TruckStop.objects.create(
            opis_id=1, name=name, address='', city='', state='OK', rack_id=1,
            retail_price=price, lat=lat, lng=lng,
        )

    def test_keeps_stops_on_or_near_the_route_and_drops_far_ones(self):
        self.make_stop('on', 35.0, -95.0)
        self.make_stop('near', 35.05, -97.0)  # about 3.5 miles north
        self.make_stop('far', 36.0, -95.0)  # about 69 miles north
        self.make_stop('outside box', 35.0, -80.0)

        found = find_stops_along_route(self.ROUTE)

        self.assertEqual({stop.name for stop, _, _ in found}, {'on', 'near'})

    def test_mile_marker_is_distance_along_the_route(self):
        self.make_stop('mid', 35.0, -95.0)

        [(stop, mile, price)] = find_stops_along_route(self.ROUTE)

        self.assertAlmostEqual(mile, haversine_miles(35.0, -100.0, 35.0, -95.0), delta=1)

    def test_returns_price_as_float_sorted_by_mile_marker(self):
        self.make_stop('later', 35.0, -92.0, price='3.10')
        self.make_stop('earlier', 35.0, -98.0, price='3.90')

        found = find_stops_along_route(self.ROUTE)

        self.assertEqual([stop.name for stop, _, _ in found], ['earlier', 'later'])
        self.assertEqual([price for _, _, price in found], [3.9, 3.1])
        self.assertLess(found[0][1], found[1][1])

    def test_ignores_stops_without_coordinates(self):
        TruckStop.objects.create(
            opis_id=2, name='no coords', address='', city='', state='OK', rack_id=1, retail_price='3.50',
        )

        self.assertEqual(find_stops_along_route(self.ROUTE), [])

    def test_tolerance_is_adjustable(self):
        self.make_stop('near', 35.1, -97.0)  # about 7 miles north

        self.assertEqual(len(find_stops_along_route(self.ROUTE, tolerance_miles=10)), 1)
        self.assertEqual(find_stops_along_route(self.ROUTE, tolerance_miles=5), [])


class PlanFuelStopsTests(SimpleTestCase):
    # Stations are (stop, mile_marker, price); the planner treats the stop as opaque.

    def test_short_trip_needs_no_fuel_purchase(self):
        stations = [('near start', 20, 3.00), ('cheaper', 150, 2.00)]

        plan = plan_fuel_stops(stations, total_miles=300)

        self.assertEqual(plan['stops'], [])
        self.assertEqual(plan['total_gallons'], 0)
        self.assertEqual(plan['total_cost'], 0)

    def test_short_trip_needs_no_stations_at_all(self):
        plan = plan_fuel_stops([], total_miles=300)

        self.assertEqual(plan['stops'], [])
        self.assertEqual(plan['total_cost'], 0)

    def test_long_trip_buys_at_several_stops(self):
        stations = [('a', 50, 3.00), ('b', 400, 3.20), ('c', 700, 3.10), ('d', 900, 3.30), ('e', 1100, 3.00)]

        plan = plan_fuel_stops(stations, total_miles=1200)

        self.assertEqual([s['stop'] for s in plan['stops']], ['a', 'b', 'c', 'e'])
        self.assertEqual([round(s['gallons'], 6) for s in plan['stops']], [5, 15, 40, 10])
        # 5 @ 3.00 + 15 @ 3.20 + 40 @ 3.10 + 10 @ 3.00
        self.assertAlmostEqual(plan['total_cost'], 15 + 48 + 124 + 30)
        # The first 500 miles ran on the starting tank, so only the other 700 miles were bought.
        self.assertAlmostEqual(plan['total_gallons'], 70)

    def test_skips_an_expensive_station(self):
        stations = [('near start', 10, 3.50), ('expensive', 400, 5.00), ('cheap', 450, 3.00)]

        plan = plan_fuel_stops(stations, total_miles=800)

        self.assertEqual([s['stop'] for s in plan['stops']], ['cheap'])
        self.assertAlmostEqual(plan['stops'][0]['gallons'], 30)
        self.assertAlmostEqual(plan['total_cost'], 30 * 3.00)

    def test_never_drives_more_than_the_range_between_stops(self):
        stations = [(f's{mile}', mile, 3.00 + (mile % 7) / 10) for mile in range(20, 2000, 60)]

        plan = plan_fuel_stops(stations, total_miles=2000)

        marks = [0] + [s['mile'] for s in plan['stops']] + [2000]
        self.assertTrue(all(b - a <= 500 for a, b in zip(marks, marks[1:])))

    def test_gap_longer_than_the_range_raises(self):
        stations = [('s', 10, 3.00), ('t', 900, 3.00)]

        with self.assertRaises(FuelPlanError):
            plan_fuel_stops(stations, total_miles=1500)

    def test_long_trip_with_no_stations_raises(self):
        with self.assertRaises(FuelPlanError):
            plan_fuel_stops([], total_miles=1500)


@patch('optimal_fuel_route.calculate.views.get_route')
class RouteEndpointTests(TestCase):
    DALLAS = (32.78, -96.80)
    CHICAGO = (41.88, -87.63)

    def setUp(self):
        cache.clear()
        Place.objects.create(state='TX', key='dallas', lat=self.DALLAS[0], lng=self.DALLAS[1])
        Place.objects.create(state='IL', key='chicago', lat=self.CHICAGO[0], lng=self.CHICAGO[1])
        self.route = [
            (self.DALLAS[0] + (self.CHICAGO[0] - self.DALLAS[0]) * i / 100,
             self.DALLAS[1] + (self.CHICAGO[1] - self.DALLAS[1]) * i / 100)
            for i in range(101)
        ]

    def add_stop(self, name, fraction, price):
        lat, lng = self.route[round(fraction * 100)]
        return TruckStop.objects.create(
            opis_id=1, name=name, address='I-35', city='X', state='TX', rack_id=1, retail_price=price,
            lat=lat, lng=lng,
        )

    def post(self, **body):
        return self.client.post('/api/route/', body, content_type='application/json')

    def test_returns_route_stops_and_cost(self, mock_get_route):
        mock_get_route.return_value = (self.route, 800.0)
        self.add_stop('first', 0.3, '3.10')
        self.add_stop('second', 0.6, '3.00')
        self.add_stop('third', 0.9, '3.20')

        response = self.post(start='Dallas, TX', finish='Chicago, IL')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['distance_miles'], 800.0)
        # The starting tank covers the first 500 miles, so 300 miles are bought at the cheapest stop.
        self.assertEqual([s['name'] for s in data['fuel_stops']], ['second'])
        self.assertEqual(data['fuel_stops'][0]['gallons'], 30.0)
        self.assertEqual(data['total_gallons'], 30.0)
        self.assertEqual(data['total_cost'], 90.0)

        features = data['map']['features']
        self.assertEqual([f['geometry']['type'] for f in features], ['LineString', 'Point'])
        self.assertEqual(features[0]['geometry']['coordinates'][0], [self.DALLAS[1], self.DALLAS[0]])
        self.assertEqual(features[1]['properties']['name'], 'second')

    def test_calls_the_routing_service_once_with_resolved_coordinates(self, mock_get_route):
        mock_get_route.return_value = (self.route, 400.0)

        self.post(start='dallas, tx', finish='Chicago, IL')

        mock_get_route.assert_called_once_with(self.DALLAS, self.CHICAGO)

    def test_trip_within_one_tank_needs_no_stops(self, mock_get_route):
        mock_get_route.return_value = (self.route, 400.0)

        response = self.post(start='Dallas, TX', finish='Chicago, IL')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fuel_stops'], [])
        self.assertEqual(response.json()['total_cost'], 0)

    def test_unknown_city_is_a_400(self, mock_get_route):
        response = self.post(start='Nowhereville, TX', finish='Chicago, IL')

        self.assertEqual(response.status_code, 400)
        self.assertIn('start', response.json())
        mock_get_route.assert_not_called()

    def test_wrong_format_is_a_400(self, mock_get_route):
        response = self.post(start='Dallas', finish='Chicago, IL')

        self.assertEqual(response.status_code, 400)
        self.assertIn('start', response.json())

    def test_missing_field_is_a_400(self, mock_get_route):
        response = self.post(start='Dallas, TX')

        self.assertEqual(response.status_code, 400)
        self.assertIn('finish', response.json())

    def test_routing_service_failure_is_a_502(self, mock_get_route):
        mock_get_route.side_effect = requests.HTTPError('401 for url https://api.example/?key=secret')

        response = self.post(start='Dallas, TX', finish='Chicago, IL')

        self.assertEqual(response.status_code, 502)
        self.assertNotIn('secret', response.content.decode())

    def test_gap_longer_than_the_range_is_a_422(self, mock_get_route):
        mock_get_route.return_value = (self.route, 800.0)  # no truck stops on the route

        response = self.post(start='Dallas, TX', finish='Chicago, IL')

        self.assertEqual(response.status_code, 422)
        self.assertIn('detail', response.json())

    def test_repeat_trip_skips_the_routing_service(self, mock_get_route):
        mock_get_route.return_value = (self.route, 400.0)

        first = self.post(start='Dallas, TX', finish='Chicago, IL')
        second = self.post(start='dallas, tx', finish='Chicago, IL')

        self.assertEqual(mock_get_route.call_count, 1)
        self.assertEqual(first.json(), second.json())

    def test_other_trips_are_not_served_from_the_cache(self, mock_get_route):
        mock_get_route.return_value = (self.route, 400.0)

        self.post(start='Dallas, TX', finish='Chicago, IL')
        self.post(start='Chicago, IL', finish='Dallas, TX')

        self.assertEqual(mock_get_route.call_count, 2)

    def test_routing_failures_are_not_cached(self, mock_get_route):
        mock_get_route.side_effect = [requests.HTTPError('503'), (self.route, 400.0)]

        failed = self.post(start='Dallas, TX', finish='Chicago, IL')
        retried = self.post(start='Dallas, TX', finish='Chicago, IL')

        self.assertEqual(failed.status_code, 502)
        self.assertEqual(retried.status_code, 200)


class MapPageTests(SimpleTestCase):
    def test_renders_the_map_with_the_requested_cities(self):
        response = self.client.get('/map/', {'start': 'Dallas, TX', 'finish': 'Chicago, IL'})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'calculate/map.html')
        self.assertContains(response, 'leaflet')
        self.assertContains(response, 'id="params"')
        self.assertContains(response, '"start": "Dallas, TX"')

    def test_renders_without_cities(self):
        response = self.client.get('/map/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"start": ""')

    def test_escapes_the_cities_it_embeds(self):
        response = self.client.get('/map/', {'start': '</script><script>alert(1)</script>', 'finish': 'x'})

        self.assertNotContains(response, '</script><script>alert(1)')
