from django.urls import path

from . import views

urlpatterns = [
    path("lecturas/", views.LecturaCreateView.as_view(), name="api-lecturas"),
    path("comandos/pendientes/", views.ComandosPendientesView.as_view(), name="api-comandos-pendientes"),
    path("comandos/<int:pk>/ejecutado/", views.ComandoEjecutadoView.as_view(), name="api-comando-ejecutado"),
    path("dispositivos/solicitar-vinculo/", views.SolicitarVinculoView.as_view(), name="api-solicitar-vinculo"),
    path("dispositivos/vinculo/<str:chip_id>/estado/", views.EstadoVinculoView.as_view(), name="api-estado-vinculo"),
    path("dispositivos/<uuid:device_id>/lecturas-recientes/", views.LecturasRecientesView.as_view(), name="api-lecturas-recientes"),
    path("comparar-lecturas/", views.ComparativaLecturasView.as_view(), name="api-comparar-lecturas"),
    path("dispositivos/<uuid:device_id>/sesiones/comparar/", views.SesionesComparativaView.as_view(), name="api-sesiones-comparar"),
]
