from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from devices.models import Comando

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
