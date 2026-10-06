from rest_framework import generics

from optimal_fuel_route.calculate.models import TruckStop
from optimal_fuel_route.calculate.serializers import TruckStopSerializer


class TruckStopList(generics.ListCreateAPIView):
    queryset = TruckStop.objects.all()
    serializer_class = TruckStopSerializer


class TruckStopDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = TruckStop.objects.all()
    serializer_class = TruckStopSerializer
