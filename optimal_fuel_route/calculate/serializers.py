from rest_framework import serializers

from optimal_fuel_route.calculate.locations import normalize_city
from optimal_fuel_route.calculate.models import Place, TruckStop


class TruckStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = TruckStop
        fields = ['id', 'opis_id', 'name', 'address', 'city', 'state', 'rack_id', 'retail_price', 'lat', 'lng']


def resolve_place(value):
    """Turn 'City, ST' into the (lat, lng) of that place."""
    city, comma, state = value.rpartition(',')
    state = state.strip().upper()
    if not comma or len(state) != 2:
        raise serializers.ValidationError('Use the format "City, ST".')

    place = Place.objects.filter(state=state, key=normalize_city(city)).first()
    if place is None:
        raise serializers.ValidationError(f'Could not find "{value}" in the USA.')
    return place.lat, place.lng


class RouteRequestSerializer(serializers.Serializer):
    """start and finish come in as 'City, ST' and leave validation as (lat, lng) pairs."""

    start = serializers.CharField()
    finish = serializers.CharField()

    def validate_start(self, value):
        return resolve_place(value)

    def validate_finish(self, value):
        return resolve_place(value)
