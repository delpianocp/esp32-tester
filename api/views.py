from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from devices.models import Comando, Device, SolicitudVinculo, generar_codigo_vinculo

from .authentication import DeviceApiKeyAuthentication
from .serializers import ComandoSerializer, LecturaSerializer


class LecturaCreateView(APIView):
    """
    POST /api/lecturas/
    Header: Authorization: Api-Key <api_key>
    Body: {"valor": 123.45, "metadata": {...opcional...}}
    """

    authentication_classes = [DeviceApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        device = request.user  # el "user" autenticado es el Device
        serializer = LecturaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(device=device)

        device.ultima_conexion = timezone.now()
        device.save(update_fields=["ultima_conexion"])

        return Response(serializer.data, status=201)


class ComandosPendientesView(APIView):
    """
    GET /api/comandos/pendientes/
    El ESP32 consulta esto periódicamente (polling) para ver si tiene
    comandos nuevos que ejecutar. Al leerlos, se marcan como 'entregado'.
    """

    authentication_classes = [DeviceApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        device = request.user
        comandos = Comando.objects.filter(device=device, estado="pendiente")
        data = ComandoSerializer(comandos, many=True).data

        comandos.update(estado="entregado", entregado_en=timezone.now())

        return Response(data)


class ComandoEjecutadoView(APIView):
    """
    POST /api/comandos/<id>/ejecutado/
    El ESP32 confirma que ya ejecutó el comando.
    """

    authentication_classes = [DeviceApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        device = request.user
        try:
            comando = Comando.objects.get(pk=pk, device=device)
        except Comando.DoesNotExist:
            return Response({"detail": "No encontrado."}, status=404)

        comando.estado = "ejecutado"
        comando.save(update_fields=["estado"])
        return Response(ComandoSerializer(comando).data)


class SolicitarVinculoView(APIView):
    """
    POST /api/dispositivos/solicitar-vinculo/
    Sin autenticación (el ESP32 todavía no tiene API Key).
    Body: {"chip_id": "A1B2C3D4E5"}

    El ESP32 llama esto al arrancar (después de conectarse a WiFi) si
    todavía no tiene una API Key guardada. El servidor crea o recupera
    una solicitud pendiente y le devuelve un código corto para mostrar
    (por Serial, o eventualmente en una pantalla/LED).
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        chip_id = request.data.get("chip_id", "").strip()
        if not chip_id:
            return Response({"detail": "Falta chip_id."}, status=400)

        solicitud, creada = SolicitudVinculo.objects.get_or_create(
            chip_id=chip_id,
            defaults={"estado": "pendiente"},
        )

        # Si quedó en un estado inconsistente (vinculado pero sin device,
        # por ejemplo porque se borró el dispositivo), la reseteamos.
        if solicitud.estado == "vinculado" and not solicitud.device:
            solicitud.estado = "pendiente"
            solicitud.codigo = generar_codigo_vinculo()
            solicitud.save(update_fields=["estado", "codigo", "actualizado_en"])

        # Si ya estaba vinculado de antes (con device real), le devolvemos directo la API Key
        if solicitud.estado == "vinculado" and solicitud.device:
            return Response({
                "estado": "vinculado",
                "codigo": solicitud.codigo,
                "api_key": solicitud.device.api_key,
                "device_id": str(solicitud.device.id),
            })

        return Response({
            "estado": solicitud.estado,
            "codigo": solicitud.codigo,
        })


class EstadoVinculoView(APIView):
    """
    GET /api/dispositivos/vinculo/<chip_id>/estado/
    Sin autenticación. El ESP32 hace polling acá cada pocos segundos
    esperando que algún usuario lo vincule desde la web.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, chip_id):
        try:
            solicitud = SolicitudVinculo.objects.get(chip_id=chip_id)
        except SolicitudVinculo.DoesNotExist:
            return Response({"detail": "Solicitud no encontrada."}, status=404)

        if solicitud.estado == "vinculado" and not solicitud.device:
            solicitud.estado = "pendiente"
            solicitud.codigo = generar_codigo_vinculo()
            solicitud.save(update_fields=["estado", "codigo", "actualizado_en"])

        if solicitud.estado == "vinculado" and solicitud.device:
            return Response({
                "estado": "vinculado",
                "api_key": solicitud.device.api_key,
                "device_id": str(solicitud.device.id),
            })

        return Response({"estado": solicitud.estado, "codigo": solicitud.codigo})