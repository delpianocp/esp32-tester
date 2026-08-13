import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


def generar_api_key():
    return secrets.token_hex(20)  # 40 caracteres


def generar_codigo_vinculo():
    # Código corto, fácil de mostrar/leer: 4 caracteres alfanuméricos en mayúscula
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin O/0/I/1 para evitar confusión
    return "".join(secrets.choice(alfabeto) for _ in range(4))


class Device(models.Model):
    TIPO_SENSOR_CHOICES = [
        ("generico", "Genérico (sin unidad)"),
        ("temperatura", "Temperatura (°C)"),
        ("corriente", "Corriente (A)"),
        ("db", "Decibeles (dB)"),
        ("binario", "Estado (ON/OFF)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=100)
    ubicacion = models.CharField(max_length=150, blank=True)
    descripcion = models.TextField(blank=True)
    tipo_sensor = models.CharField(max_length=20, choices=TIPO_SENSOR_CHOICES, default="generico")
    grupo = models.CharField(
        max_length=100, blank=True,
        help_text=(
            "Opcional. Agrupá dispositivos que dependen del mismo origen (ej: la "
            "misma PC puente, el mismo edificio). Si TODOS los dispositivos de un "
            "grupo quedan offline al mismo tiempo, Lumbre lo interpreta como un "
            "corte general (de luz o de red) en ese origen, en vez de fallas "
            "individuales, y te avisa de forma diferenciada."
        ),
    )
    etiqueta_on = models.CharField(
        max_length=20, default="ON", blank=True,
        help_text="Solo para sensores tipo 'Estado'. Texto para el valor activo (ej: ON, Arriba, Lleno)."
    )
    etiqueta_off = models.CharField(
        max_length=20, default="OFF", blank=True,
        help_text="Solo para sensores tipo 'Estado'. Texto para el valor inactivo (ej: OFF, Abajo, Vacío)."
    )
    intervalo_offline_segundos = models.PositiveIntegerField(
        default=120,
        help_text=(
            "Si no llega ninguna lectura en este tiempo (segundos), el dispositivo "
            "pasa a mostrarse como Offline. Un ESP32 que manda cada 10s puede usar "
            "el default (120s). Si viene de un script/puente que manda cada 5 min, "
            "poné algo como 600-900 para darle margen."
        ),
    )
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
    def unidad(self):
        return {"temperatura": "°C", "corriente": "A", "db": "dB", "binario": "", "generico": ""}.get(self.tipo_sensor, "")

    @property
    def tiene_sesion_activa(self):
        return self.sesiones.filter(fin__isnull=True).exists()

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

        return (timezone.now() - self.ultima_conexion).total_seconds() < self.intervalo_offline_segundos


class SesionMedicion(models.Model):
    """
    Permite "cortar" las lecturas de un dispositivo en tramos con nombre
    propio - útil cuando el mismo sensor físico se va moviendo (por
    ejemplo, medir la Línea A un rato, después la Línea B, etc.) y no
    querés que los datos de una se mezclen con los de la otra.

    Mientras una sesión está "abierta" (fin=None), todas las lecturas
    nuevas que llegan de ese dispositivo quedan etiquetadas con ella.
    """

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="sesiones")
    nombre = models.CharField(max_length=100, help_text="Ej: Línea A - Tablero principal")
    inicio = models.DateTimeField(auto_now_add=True)
    fin = models.DateTimeField(null=True, blank=True)
    duracion_minutos = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Opcional. Si lo completás, la sesión se finaliza sola después de este tiempo (cronómetro).",
    )

    class Meta:
        ordering = ["-inicio"]

    def __str__(self):
        return f"{self.device.nombre} — {self.nombre}"

    @property
    def activa(self):
        return self.fin is None

    @property
    def fin_estimado(self):
        if self.duracion_minutos:
            return self.inicio + timedelta(minutes=self.duracion_minutos)
        return None


class Lectura(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="lecturas")
    sesion = models.ForeignKey(
        SesionMedicion, on_delete=models.SET_NULL, null=True, blank=True, related_name="lecturas"
    )
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


class SolicitudVinculo(models.Model):
    """
    Representa un ESP32 que se prendió, se conectó a WiFi, y está
    'tocando la puerta' pidiendo que algún usuario lo vincule a su cuenta.
    Es el equivalente al "emparejamiento" de dispositivos smart-home.
    """

    ESTADOS = [
        ("pendiente", "Esperando vinculación"),
        ("vinculado", "Vinculado"),
    ]

    chip_id = models.CharField(max_length=32, unique=True, help_text="Identificador único de fábrica del ESP32")
    codigo = models.CharField(max_length=4, default=generar_codigo_vinculo)
    estado = models.CharField(max_length=20, choices=ESTADOS, default="pendiente")
    device = models.OneToOneField(
        Device, on_delete=models.CASCADE, null=True, blank=True, related_name="solicitud_vinculo"
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.chip_id} ({self.codigo}) - {self.estado}"


def cerrar_sesiones_vencidas(device):
    """
    Revisa las sesiones de medición abiertas de un dispositivo que
    tienen "cronómetro" (duracion_minutos), y cierra las que ya
    cumplieron su tiempo. Se llama antes de cualquier operación que
    necesite saber cuál es la sesión activa "de verdad" en este momento
    (recibir una lectura nueva, mostrar la página de sesiones, etc.) -
    no hay un proceso en segundo plano corriendo solo, así que esta
    función es la que "hace tic" cada vez que algo toca al dispositivo.
    """
    ahora = timezone.now()
    for sesion in device.sesiones.filter(fin__isnull=True, duracion_minutos__isnull=False):
        limite = sesion.inicio + timedelta(minutes=sesion.duracion_minutos)
        if ahora >= limite:
            sesion.fin = limite
            sesion.save(update_fields=["fin"])


class HistorialSensor(models.Model):
    """
    Archivo histórico de un sensor, INDEPENDIENTE del Device: cuando un
    dispositivo se desvincula/elimina, sus lecturas normalmente se
    borran en cascada - este modelo guarda una copia que sobrevive,
    identificada por el nombre del sensor, para poder consultar sus
    mediciones pasadas aunque el dispositivo ya no exista.
    """

    nombre_sensor = models.CharField(max_length=100)
    device_id_original = models.UUIDField(
        null=True, blank=True,
        help_text="El ID que tenía el Device cuando existía (referencia, no FK)."
    )
    valor = models.FloatField()
    timestamp = models.DateTimeField()
    archivado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["nombre_sensor", "-timestamp"])]
        verbose_name = "Lectura archivada"
        verbose_name_plural = "Historial de sensores"

    def __str__(self):
        return f"{self.nombre_sensor}: {self.valor} ({self.timestamp:%d/%m/%Y %H:%M})"


def archivar_lecturas_de_device(device, solo_ultimos_dias=None):
    """
    Copia lecturas de un dispositivo al archivo histórico (HistorialSensor).

    - Sin parámetros: copia TODO (se usa antes de eliminar el dispositivo,
      para que los datos sobrevivan a la desvinculación).
    - Con solo_ultimos_dias=N: solo copia los últimos N días. Evita
      timeouts en requests HTTP cuando el dispositivo tiene muchas lecturas.

    Usa bulk_create en lotes para no hacer una query por lectura, y
    evita duplicar: no copia lecturas cuyo timestamp ya exista en el
    historial para ese sensor.
    """
    qs = device.lecturas.all().only("valor", "timestamp")
    if solo_ultimos_dias:
        desde = timezone.now() - timedelta(days=solo_ultimos_dias)
        qs = qs.filter(timestamp__gte=desde)

    # Evitar duplicados: ver cuáles timestamps ya están archivados
    timestamps_existentes = set(
        HistorialSensor.objects
        .filter(nombre_sensor=device.nombre)
        .values_list("timestamp", flat=True)
    )

    lote = [
        HistorialSensor(
            nombre_sensor=device.nombre,
            device_id_original=device.id,
            valor=l.valor,
            timestamp=l.timestamp,
        )
        for l in qs
        if l.timestamp not in timestamps_existentes
    ]
    if lote:
        HistorialSensor.objects.bulk_create(lote, batch_size=500)
    return len(lote)
