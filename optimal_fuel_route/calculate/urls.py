from django.urls import path

from optimal_fuel_route.calculate import views

urlpatterns = [
    path('api/route/', views.RouteView.as_view()),
    path('truckstops/', views.TruckStopList.as_view()),
    path('truckstops/<int:pk>/', views.TruckStopDetail.as_view()),
]
