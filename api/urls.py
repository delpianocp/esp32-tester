from django.urls import path

from . import views

urlpatterns = [
    path("lecturas/", views.LecturaCreateView.as_view(), name="api-lecturas"),
    path("comandos/pendientes/", views.ComandosPendientesView.as_view(), name="api-comandos-pendientes"),
    path("comandos/<int:pk>/ejecutado/", views.ComandoEjecutadoView.as_view(), name="api-comando-ejecutado"),
]
