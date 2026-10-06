from rest_framework import serializers

from optimal_fuel_route.calculate.models import TruckStop


class TruckStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = TruckStop
        fields = ['id', 'opis_id', 'name', 'address', 'city', 'state', 'rack_id', 'retail_price', 'lat', 'lng']
