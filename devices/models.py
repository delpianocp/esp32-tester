import secrets
import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse


def generar_api_key():
    return secrets.token_hex(20)  # 40 caracteres


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=100)
    ubicacion = models.CharField(max_length=150, blank=True)
    descripcion = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="devices",
    )
    api_key = models.CharField(max_length=40, unique=True, default=generar_api_key, editable=False)
    activo = models.BooleanField(default=True)
    ultima_conexion = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]

    def __str__(self):
        return self.nombre

    @property
    def is_authenticated(self):
        """Permite que DRF trate a Device como un 'usuario' autenticado vía API key."""
        return True

    def get_absolute_url(self):
        return reverse("devices:detail", kwargs={"pk": self.pk})

    def regenerar_api_key(self):
        self.api_key = generar_api_key()
        self.save(update_fields=["api_key"])

    @property
    def online(self):
        """Se considera online si mandó una lectura en los últimos 2 minutos."""
        if not self.ultima_conexion:
            return False
        from django.utils import timezone

        return (timezone.now() - self.ultima_conexion).total_seconds() < 120


class Lectura(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="lecturas")
    valor = models.FloatField(help_text="Valor principal medido por la bobina")
    metadata = models.JSONField(blank=True, null=True, help_text="Datos extra opcionales")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["device", "-timestamp"])]

    def __str__(self):
        return f"{self.device.nombre} - {self.valor} ({self.timestamp:%Y-%m-%d %H:%M:%S})"


class Comando(models.Model):
    """Comandos que el usuario envía al ESP32 (para interactuar, ej. encender relé, cambiar modo)."""

    ESTADOS = [
        ("pendiente", "Pendiente"),
        ("entregado", "Entregado"),
        ("ejecutado", "Ejecutado"),
    ]

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="comandos")
    accion = models.CharField(max_length=50, help_text="Ej: ON, OFF, RESET, SET_MODO")
    parametro = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default="pendiente")
    creado_en = models.DateTimeField(auto_now_add=True)
    entregado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.device.nombre}: {self.accion} ({self.estado})"
