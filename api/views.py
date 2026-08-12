from datetime import datetime

from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from devices.models import Comando, Device, SolicitudVinculo, archivar_lecturas_de_device, cerrar_sesiones_vencidas, generar_codigo_vinculo

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

        # Si el dispositivo tiene una sesión de medición abierta (ver
        # SesionMedicion), esta lectura queda etiquetada con ella - así
        # se puede diferenciar más adelante de qué "tramo" vino cada dato.
        # Si había una sesión con cronómetro que ya venció, la cerramos
        # antes de decidir a cuál sesión pertenece esta lectura.
        cerrar_sesiones_vencidas(device)
        sesion_activa = device.sesiones.filter(fin__isnull=True).first()
        serializer.save(device=device, sesion=sesion_activa)

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

    Caso especial: si el comando era RESET (se manda cuando el usuario
    elimina el dispositivo desde la web), al confirmarlo se borra el
    Device de la base — recién ahí, no antes, para asegurarnos de que el
    ESP32 alcanzó a recibir la orden antes de perder su API Key.
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
        data = ComandoSerializer(comando).data

        if comando.accion == "RESET":
            archivar_lecturas_de_device(device)
            device.delete()

        return Response(data)


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


class LecturasRecientesView(APIView):
    """
    GET /api/dispositivos/<uuid:device_id>/lecturas-recientes/
    GET /api/dispositivos/<uuid:device_id>/lecturas-recientes/?fecha=2026-08-04

    Público (sin autenticación) - lo usa la página web del detalle del
    dispositivo para actualizar el gráfico en tiempo real vía polling.

    Sin parámetro 'fecha': trae las últimas 100 lecturas (comportamiento
    de siempre, para el polling en vivo).

    Con 'fecha' (formato YYYY-MM-DD): trae TODAS las lecturas de ese día
    específico (hasta un máximo de 1000, por las dudas), para el selector
    de calendario en el gráfico histórico.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, device_id):
        try:
            device = Device.objects.get(pk=device_id)
        except Device.DoesNotExist:
            return Response({"detail": "Dispositivo no encontrado."}, status=404)

        fecha_str = request.query_params.get("fecha")
        sesion_id = request.query_params.get("sesion")

        if sesion_id:
            # Todas las lecturas de UNA sesión de medición puntual,
            # sin importar cuántos días haya durado (para el gráfico en
            # vivo de la página de sesiones).
            lecturas = device.lecturas.filter(sesion_id=sesion_id).order_by("timestamp")[:15000]
            data = [
                {"timestamp": l.timestamp.isoformat(), "valor": l.valor}
                for l in lecturas
            ]
        elif fecha_str:
            try:
                fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({"detail": "Formato de fecha inválido. Usá YYYY-MM-DD."}, status=400)

            # Límite generoso: el sensor más rápido (corriente, cada 10s)
            # puede generar hasta ~8640 lecturas en un día completo. Antes
            # este límite estaba en 1000, lo que "congelaba" el gráfico
            # después de las primeras ~2.75hs del día.
            lecturas = device.lecturas.filter(timestamp__date=fecha).order_by("timestamp")[:15000]
            data = [
                {"timestamp": l.timestamp.isoformat(), "valor": l.valor}
                for l in lecturas
            ]
        else:
            lecturas = device.lecturas.all()[:100]
            data = [
                {"timestamp": l.timestamp.isoformat(), "valor": l.valor}
                for l in reversed(lecturas)
            ]

        return Response({
            "online": device.online,
            "ultima_conexion": device.ultima_conexion.isoformat() if device.ultima_conexion else None,
            "lecturas": data,
        })


class ComparativaLecturasView(APIView):
    """
    GET /api/comparar-lecturas/?ids=uuid1,uuid2,uuid3&fecha=YYYY-MM-DD

    Trae las lecturas de un día para varios dispositivos a la vez (deben
    ser todos del mismo tipo de sensor, se valida del lado del cliente
    antes de pedir esto). Requiere estar logueado - es la vista de
    comparación, no el detalle público de un dispositivo individual.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ids_str = request.query_params.get("ids", "")
        fecha_str = request.query_params.get("fecha")

        if not ids_str or not fecha_str:
            return Response({"detail": "Faltan parámetros 'ids' y/o 'fecha'."}, status=400)

        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            return Response({"detail": "Formato de fecha inválido. Usá YYYY-MM-DD."}, status=400)

        ids = [i.strip() for i in ids_str.split(",") if i.strip()]
        resultado = []

        for device_id in ids:
            try:
                device = Device.objects.get(pk=device_id)
            except (Device.DoesNotExist, ValueError):
                continue

            lecturas = device.lecturas.filter(timestamp__date=fecha).order_by("timestamp")[:15000]
            resultado.append({
                "id": str(device.id),
                "nombre": device.nombre,
                "unidad": device.unidad,
                "lecturas": [
                    {"timestamp": l.timestamp.isoformat(), "valor": l.valor}
                    for l in lecturas
                ],
            })

        return Response({"dispositivos": resultado})


class SesionesComparativaView(APIView):
    """
    GET /api/dispositivos/<uuid:device_id>/sesiones/comparar/

    Trae TODAS las sesiones de medición finalizadas de un dispositivo,
    con cada lectura expresada como "segundos desde el inicio de la
    sesión" (no la hora real) - así se pueden superponer aunque las
    sesiones hayan ocurrido en días distintos. Solo el dueño puede verlo.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        try:
            device = Device.objects.get(pk=device_id)
        except Device.DoesNotExist:
            return Response({"detail": "Dispositivo no encontrado."}, status=404)

        if device.owner_id != request.user.id:
            return Response({"detail": "No tenés permiso para ver esto."}, status=403)

        sesiones = device.sesiones.filter(fin__isnull=False).order_by("inicio")
        resultado = []

        for sesion in sesiones:
            lecturas = sesion.lecturas.order_by("timestamp")
            puntos = []
            for l in lecturas:
                offset_segundos = (l.timestamp - sesion.inicio).total_seconds()
                puntos.append({"offset_segundos": offset_segundos, "valor": l.valor})

            if puntos:
                resultado.append({
                    "id": sesion.id,
                    "nombre": sesion.nombre,
                    "puntos": puntos,
                })

        return Response({"unidad": device.unidad, "sesiones": resultado})
