from django.urls import path

from . import views

app_name = "devices"

urlpatterns = [
    path("", views.device_list, name="list"),
    path("mios/", views.my_devices, name="my_devices"),
    path("agregar/", views.device_create, name="create"),
    path("<uuid:pk>/", views.device_detail, name="detail"),
]
