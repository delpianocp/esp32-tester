from django.urls import path

from . import views

app_name = "devices"

urlpatterns = [
    path("", views.device_list, name="list"),
    path("mios/", views.my_devices, name="my_devices"),
    path("agregar/", views.device_create, name="create"),
    path("vincular/", views.solicitudes_vinculo, name="solicitudes_vinculo"),
    path("vincular/<int:solicitud_id>/", views.vincular_dispositivo, name="vincular"),
    path("vincular/<int:solicitud_id>/descartar/", views.descartar_solicitud, name="descartar_solicitud"),
    path("<uuid:pk>/eliminar/", views.device_delete, name="delete"),
    path("<uuid:pk>/", views.device_detail, name="detail"),
]
