from django.contrib import admin

from .models import Comando, Device, Lectura, SolicitudVinculo


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("nombre", "owner", "activo", "online", "ultima_conexion", "creado_en")
    list_filter = ("activo",)
    search_fields = ("nombre", "owner__username")
    readonly_fields = ("id", "api_key", "creado_en")


@admin.register(Lectura)
class LecturaAdmin(admin.ModelAdmin):
    list_display = ("device", "valor", "timestamp")
    list_filter = ("device",)
    date_hierarchy = "timestamp"


@admin.register(Comando)
class ComandoAdmin(admin.ModelAdmin):
    list_display = ("device", "accion", "parametro", "estado", "creado_en")
    list_filter = ("estado", "device")


@admin.register(SolicitudVinculo)
class SolicitudVinculoAdmin(admin.ModelAdmin):
    list_display = ("chip_id", "codigo", "estado", "device", "creado_en")
    list_filter = ("estado",)
    readonly_fields = ("chip_id", "codigo", "creado_en", "actualizado_en")
