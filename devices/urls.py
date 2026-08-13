from django.urls import path

from . import views

app_name = "devices"

urlpatterns = [
    path("", views.device_list, name="list"),
    path("mios/", views.my_devices, name="my_devices"),
    path("comparar/", views.comparar_sensores, name="comparar"),
    path("comparar/pdf/", views.comparar_pdf, name="comparar_pdf"),
    path("historial/", views.historial_sensores, name="historial_sensores"),
    path("historial/<str:nombre_sensor>/", views.historial_sensor_detalle, name="historial_sensor_detalle"),
    path("vincular/", views.solicitudes_vinculo, name="solicitudes_vinculo"),
    path("vincular/<int:solicitud_id>/", views.vincular_dispositivo, name="vincular"),
    path("vincular/<int:solicitud_id>/descartar/", views.descartar_solicitud, name="descartar_solicitud"),
    path("<uuid:pk>/editar/", views.device_edit, name="edit"),
    path("<uuid:pk>/archivar/", views.archivar_lecturas, name="archivar"),
    path("<uuid:pk>/eliminar/", views.device_delete, name="delete"),
    path("<uuid:pk>/lecturas/pdf/", views.descargar_lecturas_pdf, name="lecturas_pdf"),
    path("<uuid:pk>/lecturas/eliminar/", views.eliminar_historial, name="eliminar_historial"),
    path("<uuid:pk>/sesiones/", views.sesiones_medicion, name="sesiones"),
    path("<uuid:pk>/sesiones/iniciar/", views.iniciar_sesion_medicion, name="iniciar_sesion"),
    path("<uuid:pk>/sesiones/<int:sesion_id>/finalizar/", views.finalizar_sesion_medicion, name="finalizar_sesion"),
    path("<uuid:pk>/sesiones/<int:sesion_id>/eliminar/", views.eliminar_sesion_medicion, name="eliminar_sesion"),
    path("<uuid:pk>/sesiones/<int:sesion_id>/pdf/", views.descargar_sesion_pdf, name="sesion_pdf"),
    path("<uuid:pk>/sesiones/comparar/", views.comparar_sesiones, name="comparar_sesiones"),
    path("<uuid:pk>/sesiones/comparar/pdf/", views.comparar_sesiones_pdf, name="comparar_sesiones_pdf"),
    path("<uuid:pk>/", views.device_detail, name="detail"),
]
