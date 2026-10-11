import logging

import requests
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from optimal_fuel_route.calculate.fuel import FuelPlanError, plan_fuel_stops
from optimal_fuel_route.calculate.models import TruckStop
from optimal_fuel_route.calculate.routing import get_route
from optimal_fuel_route.calculate.serializers import RouteRequestSerializer, TruckStopSerializer
from optimal_fuel_route.calculate.stations import find_stops_along_route

logger = logging.getLogger(__name__)


class TruckStopList(generics.ListCreateAPIView):
    queryset = TruckStop.objects.all()
    serializer_class = TruckStopSerializer


class TruckStopDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = TruckStop.objects.all()
    serializer_class = TruckStopSerializer


class RouteView(APIView):
    # TODO: this is a demo, so the endpoint is open and unthrottled. Every request spends OpenRouteService
    # quota; add authentication and throttling (DRF throttle classes) before exposing it.
    def post(self, request):
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            coords, miles = get_route(serializer.validated_data['start'], serializer.validated_data['finish'])
        except requests.RequestException as e:
            # Log the type and status, not the exception text: requests puts the full URL in the message.
            status_code = e.response.status_code if e.response is not None else None
            logger.warning('OpenRouteService directions failed: %s (HTTP status %s)', type(e).__name__, status_code)
            return Response(
                {'detail': 'Could not get a route from the routing service.'}, status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            plan = plan_fuel_stops(find_stops_along_route(coords), miles)
        except FuelPlanError as e:
            logger.info('No fuel plan for the route: %s', e)
            return Response({'detail': str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        stops = plan['stops']
        route_line = {
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': [[lng, lat] for lat, lng in coords]},
            'properties': {'kind': 'route'},
        }
        stop_points = [
            {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [s['stop'].lng, s['stop'].lat]},
                'properties': {
                    'kind': 'fuel_stop', 'name': s['stop'].name, 'price': round(s['price'], 3),
                    'gallons': round(s['gallons'], 2), 'cost': round(s['cost'], 2),
                },
            }
            for s in stops
        ]

        return Response({
            'distance_miles': round(miles, 1),
            'total_gallons': round(plan['total_gallons'], 2),
            'total_cost': round(plan['total_cost'], 2),
            'fuel_stops': [
                {
                    'id': s['stop'].id, 'name': s['stop'].name, 'address': s['stop'].address,
                    'city': s['stop'].city, 'state': s['stop'].state, 'lat': s['stop'].lat, 'lng': s['stop'].lng,
                    'mile': round(s['mile'], 1), 'price': round(s['price'], 3),
                    'gallons': round(s['gallons'], 2), 'cost': round(s['cost'], 2),
                }
                for s in stops
            ],
            'map': {'type': 'FeatureCollection', 'features': [route_line, *stop_points]},
        })
