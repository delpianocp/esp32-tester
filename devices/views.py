import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .account_forms import RegistroForm
from .forms import ComandoForm, DeviceForm, VincularDeviceForm
from .models import (
    Comando,
    Device,
    HistorialSensor,
    SesionMedicion,
    SolicitudVinculo,
    archivar_lecturas_de_device,
    cerrar_sesiones_vencidas,
)


def registro(request):
    if request.user.is_authenticated:
        return redirect("devices:list")

    if request.method == "POST":
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "¡Cuenta creada! Ya podés agregar tus dispositivos.")
            return redirect("devices:list")
    else:
        form = RegistroForm()

    return render(request, "registration/registro.html", {"form": form})


@login_required
def comparar_pdf(request):
    """
    Genera un PDF comparando varios dispositivos del mismo tipo de
    sensor en un mismo día: gráfico con todas las series superpuestas
    + una tabla con las lecturas agrupadas por minuto (una columna por
    dispositivo), ya que cada uno reporta en su propio horario y rara
    vez coinciden al segundo exacto.

    GET /comparar/pdf/?ids=uuid1,uuid2&fecha=YYYY-MM-DD
    """
    from datetime import datetime as dt, timedelta
    from io import BytesIO

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    from django.http import HttpResponse
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    ids_str = request.GET.get("ids", "")
    fecha_str = request.GET.get("fecha")

    ids = [i.strip() for i in ids_str.split(",") if i.strip()]
    if len(ids) < 2:
        return HttpResponse("Elegí al menos 2 dispositivos ('ids' separados por coma).", status=400)

    if fecha_str:
        try:
            fecha = dt.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            return HttpResponse("Formato de fecha inválido. Usá YYYY-MM-DD.", status=400)
    else:
        fecha = timezone.localtime(timezone.now()).date()
        fecha_str = fecha.strftime("%Y-%m-%d")

    dispositivos = []
    for device_id in ids:
        try:
            device = Device.objects.get(pk=device_id)
        except (Device.DoesNotExist, ValueError):
            continue
        lecturas = list(device.lecturas.filter(timestamp__date=fecha).order_by("timestamp"))
        dispositivos.append({"device": device, "lecturas": lecturas})

    if len(dispositivos) < 2:
        return HttpResponse("No se encontraron al menos 2 dispositivos válidos.", status=400)

    response = HttpResponse(content_type="application/pdf")
    nombre_archivo = f"lumbre_comparativa_{fecha_str}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{nombre_archivo}"'

    doc = SimpleDocTemplate(
        response, pagesize=letter,
        topMargin=1.5 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    gris_oscuro = colors.HexColor("#10231a")
    gris = colors.HexColor("#6c757d")
    navy_fondo = colors.HexColor("#0b1114")
    paleta = ["#2f9e5f", "#e8752c", "#0dcaf0", "#e83e8c", "#8b5cf6"]

    header_style = ParagraphStyle(
        "Header", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=15, textColor=colors.white, leading=18,
    )
    header_text = (
        "Lumbre <font size='9' color='#8a94a3'>para</font> "
        "<font color='#ffffff'>COPAN</font><font color='#e8752c'>SEGUROS</font>"
    )
    header_table = Table([[Paragraph(header_text, header_style)]], colWidths=[doc.width])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), navy_fondo),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
    ]))

    subtitulo_style = ParagraphStyle(
        "Subtitulo", parent=styles["Normal"], fontName="Helvetica",
        fontSize=12, textColor=gris_oscuro, spaceAfter=4, spaceBefore=18,
    )
    fecha_style = ParagraphStyle(
        "FechaGrande", parent=styles["Normal"], fontName="Helvetica",
        fontSize=10, textColor=gris, spaceAfter=14,
    )
    nombres = ", ".join(d["device"].nombre for d in dispositivos)

    story = [
        header_table,
        Spacer(1, 0),
        Paragraph("Reporte comparativo de sensores", subtitulo_style),
        Paragraph(f"{nombres} — {fecha.strftime('%d/%m/%Y')}", fecha_style),
        HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#e5e7e2"), spaceAfter=16),
    ]

    # -------------------------------------------------------------
    # Gráfico con todas las series superpuestas (mismo muestreo que
    # el reporte individual, para que no se vea como bloque sólido)
    # -------------------------------------------------------------
    def muestrear(lista_lecturas, max_puntos=150):
        lista_local = [(timezone.localtime(l.timestamp).replace(tzinfo=None), l.valor) for l in lista_lecturas]
        if len(lista_local) <= max_puntos:
            return lista_local

        inicio = lista_local[0][0]
        fin = lista_local[-1][0]
        duracion = (fin - inicio).total_seconds() or 1
        intervalo = duracion / max_puntos

        buckets = {}
        for ts, valor in lista_local:
            offset = (ts - inicio).total_seconds()
            indice = int(offset // intervalo)
            if indice not in buckets:
                buckets[indice] = {"suma": 0.0, "cantidad": 0, "t_suma": 0.0}
            b = buckets[indice]
            b["suma"] += valor
            b["t_suma"] += offset
            b["cantidad"] += 1

        resultado = []
        for indice in sorted(buckets):
            b = buckets[indice]
            t_promedio = inicio + timedelta(seconds=b["t_suma"] / b["cantidad"])
            v_promedio = round(b["suma"] / b["cantidad"], 2)
            resultado.append((t_promedio, v_promedio))
        return resultado

    fig, ax = plt.subplots(figsize=(6.8, 2.8), dpi=150)
    hay_datos = False
    for i, d in enumerate(dispositivos):
        if not d["lecturas"]:
            continue
        puntos = muestrear(d["lecturas"])
        horas_d = [p[0] for p in puntos]
        valores_d = [p[1] for p in puntos]
        color = paleta[i % len(paleta)]
        ax.plot(horas_d, valores_d, color=color, linewidth=1.6, label=d["device"].nombre)
        hay_datos = True

    if hay_datos:
        ax.set_facecolor("#ffffff")
        fig.patch.set_facecolor("#ffffff")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#c7ccc7")
        ax.spines["bottom"].set_color("#c7ccc7")
        ax.tick_params(colors="#6c757d", labelsize=8)
        ax.grid(axis="y", color="#e5e7e2", linewidth=0.6)
        ax.set_axisbelow(True)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.legend(fontsize=7, loc="upper right", frameon=False)
        fig.autofmt_xdate(rotation=0, ha="center")

        buffer = BytesIO()
        fig.tight_layout()
        fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        buffer.seek(0)

        grafico_titulo_style = ParagraphStyle(
            "GraficoTitulo", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, textColor=gris_oscuro, spaceAfter=8,
        )
        story.append(Paragraph("Evolución comparada", grafico_titulo_style))
        story.append(Image(buffer, width=doc.width, height=doc.width * (2.8 / 6.8)))
        story.append(Spacer(1, 24))
    else:
        plt.close(fig)
        story.append(Paragraph("Ninguno de los dispositivos elegidos tiene lecturas ese día.", styles["Normal"]))

    # -------------------------------------------------------------
    # Tabla agrupada por minuto: una fila por minuto, una columna
    # por dispositivo. Como cada sensor reporta en su propio horario,
    # agrupamos por minuto (no por segundo exacto) para que coincidan.
    # -------------------------------------------------------------
    if hay_datos:
        tabla_titulo_style = ParagraphStyle(
            "TablaTitulo", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, textColor=gris_oscuro, spaceAfter=10,
        )
        story.append(Paragraph("Mediciones por minuto", tabla_titulo_style))

        # minuto (HH:MM) -> {nombre_dispositivo: valor}
        filas_por_minuto = {}
        for d in dispositivos:
            for l in d["lecturas"]:
                minuto = timezone.localtime(l.timestamp).strftime("%H:%M")
                filas_por_minuto.setdefault(minuto, {})[d["device"].nombre] = l.valor

        minutos_ordenados = sorted(filas_por_minuto.keys())
        nombres_dispositivos = [d["device"].nombre for d in dispositivos]

        encabezado = ["Hora"] + nombres_dispositivos
        tabla_data = [encabezado]
        for minuto in minutos_ordenados:
            fila = [minuto]
            for nombre in nombres_dispositivos:
                valor = filas_por_minuto[minuto].get(nombre)
                fila.append(f"{valor:.2f}" if valor is not None else "—")
            tabla_data.append(fila)

        ancho_hora = 2.5 * cm
        ancho_col = (doc.width - ancho_hora) / len(nombres_dispositivos)
        anchos = [ancho_hora] + [ancho_col] * len(nombres_dispositivos)

        tabla = Table(tabla_data, colWidths=anchos, repeatRows=1)
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), gris_oscuro),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8f6")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7e2")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tabla)

    doc.build(story)
    return response


@login_required
def comparar_sensores(request):
    """
    Le permite a un usuario logueado elegir varios dispositivos del
    MISMO tipo de sensor (temperatura, corriente, dB) y verlos juntos
    en un solo gráfico comparativo.
    """
    TIPOS_COMPARABLES = ["temperatura", "corriente", "db", "generico"]

    categorias = []
    for tipo_key, tipo_label in Device.TIPO_SENSOR_CHOICES:
        if tipo_key not in TIPOS_COMPARABLES:
            continue
        dispositivos = Device.objects.filter(tipo_sensor=tipo_key).select_related("owner")
        if dispositivos.count() >= 2:
            categorias.append({
                "key": tipo_key,
                "label": tipo_label,
                "devices": dispositivos,
            })

    tipo_seleccionado = request.GET.get("tipo", "")
    categoria_actual = next((c for c in categorias if c["key"] == tipo_seleccionado), None)

    return render(request, "devices/comparar_sensores.html", {
        "categorias": categorias,
        "categoria_actual": categoria_actual,
    })


def device_list(request):
    """Home: cualquier usuario (logueado o no) puede ver todos los dispositivos."""
    devices = Device.objects.select_related("owner").all()

    # Detectamos "cortes generales": grupos donde TODOS los dispositivos
    # están offline al mismo tiempo. Si solo uno cae, es un problema de
    # ese sensor puntual; si caen todos los del mismo origen juntos, es
    # más probable que sea un corte de luz/red en ese lugar.
    grupos_caidos = []
    grupos_nombres = list(
        devices.exclude(grupo="").order_by().values_list("grupo", flat=True).distinct()
    )

    for nombre_grupo in grupos_nombres:
        dispositivos_del_grupo = [d for d in devices if d.grupo == nombre_grupo]
        if len(dispositivos_del_grupo) >= 2 and all(not d.online for d in dispositivos_del_grupo):
            ultimas_conexiones = [d.ultima_conexion for d in dispositivos_del_grupo if d.ultima_conexion]
            ultima_conexion_grupo = max(ultimas_conexiones) if ultimas_conexiones else None
            grupos_caidos.append({
                "nombre": nombre_grupo,
                "cantidad": len(dispositivos_del_grupo),
                "ultima_conexion": ultima_conexion_grupo,
            })

    # Armamos la lista para mostrar agrupada: primero cada grupo (en
    # orden alfabético), y al final los dispositivos sin grupo asignado.
    nombres_grupos_caidos = {g["nombre"] for g in grupos_caidos}
    grupos_nombres.sort()
    grupos_para_mostrar = []
    for nombre_grupo in grupos_nombres:
        dispositivos_del_grupo = [d for d in devices if d.grupo == nombre_grupo]
        grupos_para_mostrar.append({
            "nombre": nombre_grupo,
            "devices": dispositivos_del_grupo,
            "caido": nombre_grupo in nombres_grupos_caidos,
        })

    dispositivos_sin_grupo = [d for d in devices if not d.grupo]

    return render(request, "devices/device_list.html", {
        "devices": devices,
        "grupos_caidos": grupos_caidos,
        "grupos_para_mostrar": grupos_para_mostrar,
        "dispositivos_sin_grupo": dispositivos_sin_grupo,
    })


def device_detail(request, pk):
    """Detalle público: lecturas del dispositivo + posibilidad de enviar comandos."""
    device = get_object_or_404(Device, pk=pk)
    lecturas = device.lecturas.all()[:100]  # últimas 100 lecturas
    comandos = device.comandos.all()[:20]

    puede_controlar = request.user.is_authenticated and request.user == device.owner

    comando_form = None
    if puede_controlar:
        if request.method == "POST":
            comando_form = ComandoForm(request.POST)
            if comando_form.is_valid():
                comando = comando_form.save(commit=False)
                comando.device = device
                comando.save()
                messages.success(request, "Comando enviado al dispositivo.")
                return redirect("devices:detail", pk=device.pk)
        else:
            comando_form = ComandoForm()

    # Datos para el gráfico: orden cronológico ascendente (más viejo primero)
    lecturas_grafico = list(lecturas)[::-1]
    grafico_labels = [l.timestamp.strftime("%H:%M:%S") for l in lecturas_grafico]
    grafico_valores = [l.valor for l in lecturas_grafico]

    context = {
        "device": device,
        "lecturas": lecturas,
        "comandos": comandos,
        "puede_controlar": puede_controlar,
        "comando_form": comando_form,
        "grafico_labels": json.dumps(grafico_labels),
        "grafico_valores": json.dumps(grafico_valores),
        "sesiones": device.sesiones.all()[:20] if puede_controlar else None,
        "sesion_activa": device.sesiones.filter(fin__isnull=True).first() if puede_controlar else None,
    }
    return render(request, "devices/device_detail.html", context)


@login_required
def iniciar_sesion_medicion(request, pk):
    """
    Arranca una sesión de medición nueva para un dispositivo (por
    ejemplo, "Línea A"). Si ya había una sesión abierta, se cierra sola
    antes de abrir la nueva - así nunca quedan dos sesiones activas
    a la vez para el mismo dispositivo.

    Si se completa "duracion_minutos", la sesión actúa como un
    cronómetro: se cierra sola cuando se cumple ese tiempo (sin
    necesitar que nadie apriete "Finalizar" a mano).
    """
    device = get_object_or_404(Device, pk=pk, owner=request.user)

    if request.method == "POST":
        nombre = request.POST.get("nombre", "").strip()
        if not nombre:
            messages.error(request, "Ponele un nombre a la sesión (ej: 'Línea A').")
            return redirect("devices:sesiones", pk=device.pk)

        duracion_str = request.POST.get("duracion_minutos", "").strip()
        duracion_minutos = None
        if duracion_str:
            try:
                duracion_minutos = int(duracion_str)
                if duracion_minutos <= 0:
                    raise ValueError
            except ValueError:
                messages.error(request, "La duración tiene que ser un número de minutos mayor a 0.")
                return redirect("devices:sesiones", pk=device.pk)

        # Cerrar cualquier sesión que hubiera quedado abierta
        device.sesiones.filter(fin__isnull=True).update(fin=timezone.now())

        SesionMedicion.objects.create(device=device, nombre=nombre, duracion_minutos=duracion_minutos)
        if duracion_minutos:
            messages.success(request, f"Sesión '{nombre}' iniciada, se va a finalizar sola en {duracion_minutos} minutos.")
        else:
            messages.success(request, f"Sesión '{nombre}' iniciada. Las próximas lecturas quedan agrupadas ahí.")

    return redirect("devices:sesiones", pk=device.pk)


@login_required
def finalizar_sesion_medicion(request, pk, sesion_id):
    """Cierra una sesión de medición abierta."""
    device = get_object_or_404(Device, pk=pk, owner=request.user)
    sesion = get_object_or_404(SesionMedicion, pk=sesion_id, device=device, fin__isnull=True)

    if request.method == "POST":
        sesion.fin = timezone.now()
        sesion.save(update_fields=["fin"])
        messages.success(request, f"Sesión '{sesion.nombre}' finalizada.")

    return redirect("devices:sesiones", pk=device.pk)


@login_required
def eliminar_sesion_medicion(request, pk, sesion_id):
    """Borra una sesión de medición junto con todas sus lecturas."""
    device = get_object_or_404(Device, pk=pk, owner=request.user)
    sesion = get_object_or_404(SesionMedicion, pk=sesion_id, device=device)

    if request.method == "POST":
        nombre = sesion.nombre
        sesion.lecturas.all().delete()
        sesion.delete()
        messages.success(request, f"Sesión '{nombre}' eliminada.")

    return redirect("devices:sesiones", pk=device.pk)


@login_required
def eliminar_historial(request, pk):
    """
    Borra las lecturas "sueltas" (sin sesión) de un dispositivo, con
    más de 7 días de antigüedad - para no dejar acumular historial
    viejo indefinidamente. No toca las lecturas que pertenecen a una
    sesión de medición (esas se borran junto con su sesión, aparte).
    """
    device = get_object_or_404(Device, pk=pk, owner=request.user)

    if request.method == "POST":
        limite = timezone.now() - timedelta(days=7)
        borradas = device.lecturas.filter(sesion__isnull=True, timestamp__lt=limite)
        cantidad = borradas.count()
        borradas.delete()
        messages.success(request, f"Se eliminaron {cantidad} lecturas de más de 7 días.")

    return redirect("devices:detail", pk=device.pk)


@login_required
def historial_sensores(request):
    """
    Listado de todos los sensores que tienen mediciones archivadas
    (dispositivos que fueron desvinculados/eliminados). Cada uno con
    su cantidad de lecturas y rango de fechas.
    """
    from django.db.models import Count, Max, Min

    sensores = (
        HistorialSensor.objects
        .order_by()
        .values("nombre_sensor")
        .annotate(
            cantidad=Count("id"),
            desde=Min("timestamp"),
            hasta=Max("timestamp"),
        )
        .order_by("nombre_sensor")
    )

    return render(request, "devices/historial_sensores.html", {"sensores": sensores})


@login_required
def historial_sensor_detalle(request, nombre_sensor):
    """
    Mediciones archivadas de UN sensor, agrupadas por día. Cada día
    muestra sus estadísticas (mín/máx/promedio/cantidad) y se puede
    expandir para ver las lecturas una por una.
    """
    from collections import OrderedDict

    lecturas = HistorialSensor.objects.filter(nombre_sensor=nombre_sensor).order_by("-timestamp")

    if not lecturas.exists():
        messages.error(request, f"No hay historial para '{nombre_sensor}'.")
        return redirect("devices:historial_sensores")

    # Agrupamos por día (en hora local)
    dias = OrderedDict()
    for l in lecturas:
        dia = timezone.localtime(l.timestamp).date()
        if dia not in dias:
            dias[dia] = []
        dias[dia].append(l)

    dias_resumen = []
    for dia, lecturas_dia in dias.items():
        valores = [l.valor for l in lecturas_dia]
        dias_resumen.append({
            "fecha": dia,
            "cantidad": len(valores),
            "minimo": min(valores),
            "maximo": max(valores),
            "promedio": sum(valores) / len(valores),
            "lecturas": lecturas_dia,
        })

    return render(request, "devices/historial_sensor_detalle.html", {
        "nombre_sensor": nombre_sensor,
        "dias": dias_resumen,
    })


@login_required
def sesiones_medicion(request, pk):
    """
    Página propia (no desplegable) para administrar las sesiones de
    medición de un dispositivo: iniciar/finalizar, ver la que está
    activa en vivo (tabla + gráfico), y descargar las anteriores.
    """
    device = get_object_or_404(Device, pk=pk, owner=request.user)
    cerrar_sesiones_vencidas(device)
    sesion_activa = device.sesiones.filter(fin__isnull=True).first()
    sesiones_anteriores = device.sesiones.filter(fin__isnull=False).order_by("-inicio")[:30]

    return render(request, "devices/sesiones_medicion.html", {
        "device": device,
        "sesion_activa": sesion_activa,
        "sesiones_anteriores": sesiones_anteriores,
    })


@login_required
def comparar_sesiones(request, pk):
    """Muestra todas las sesiones de medición finalizadas de un dispositivo, superpuestas."""
    device = get_object_or_404(Device, pk=pk)
    sesiones = device.sesiones.filter(fin__isnull=False).order_by("inicio")
    return render(request, "devices/comparar_sesiones.html", {
        "device": device,
        "sesiones": sesiones,
    })


@login_required
def comparar_sesiones_pdf(request, pk):
    """PDF de comparación de todas las sesiones: gráfico superpuesto + tabla de estadísticas."""
    from datetime import datetime as dt, timedelta
    from io import BytesIO

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    from django.http import HttpResponse
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable, Image, Paragraph, SimpleDocTemplate,
        Spacer, Table, TableStyle,
    )

    device = get_object_or_404(Device, pk=pk)
    sesiones = device.sesiones.filter(fin__isnull=False).order_by("inicio")

    if sesiones.count() < 2:
        return HttpResponse("Se necesitan al menos 2 sesiones finalizadas.", status=400)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="lumbre_sesiones_{device.nombre}.pdf"'

    doc = SimpleDocTemplate(
        response, pagesize=letter,
        topMargin=1.5 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    verde = colors.HexColor("#2f9e5f")
    gris_oscuro = colors.HexColor("#10231a")
    gris = colors.HexColor("#6c757d")
    navy = colors.HexColor("#0b1114")
    paleta_hex = ["#2f9e5f", "#e8752c", "#0dcaf0", "#e83e8c", "#8b5cf6", "#facc15"]
    paleta_mpl = [c for c in paleta_hex]

    header_style = ParagraphStyle("Header", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=15, textColor=colors.white, leading=18)
    header_text = ("Lumbre <font size='9' color='#8a94a3'>para</font> "
        "<font color='#ffffff'>COPAN</font><font color='#e8752c'>SEGUROS</font>")
    header_table = Table([[Paragraph(header_text, header_style)]], colWidths=[doc.width])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), navy),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
    ]))

    subtitulo_style = ParagraphStyle("Subtitulo", parent=styles["Normal"],
        fontName="Helvetica", fontSize=12, textColor=gris_oscuro, spaceAfter=4, spaceBefore=18)
    fecha_style = ParagraphStyle("Fecha", parent=styles["Normal"],
        fontName="Helvetica", fontSize=10, textColor=gris, spaceAfter=14)

    story = [
        header_table, Spacer(1, 0),
        Paragraph(f"Comparación de sesiones — {device.nombre}", subtitulo_style),
        Paragraph(f"{sesiones.count()} sesiones · {device.unidad or 'sin unidad'}", fecha_style),
        HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#e5e7e2"), spaceAfter=16),
    ]

    # Gráfico con todas las sesiones superpuestas por hora real
    fig, ax = plt.subplots(figsize=(6.8, 3.0), dpi=150)
    hay_datos = False
    datasets = []

    for i, sesion in enumerate(sesiones):
        lecturas = list(sesion.lecturas.order_by("timestamp"))
        if not lecturas:
            continue
        horas = [timezone.localtime(l.timestamp).replace(tzinfo=None) for l in lecturas]
        valores = [l.valor for l in lecturas]
        color = paleta_mpl[i % len(paleta_mpl)]
        ax.plot(horas, valores, color=color, linewidth=1.4, label=sesion.nombre)
        hay_datos = True
        datasets.append((sesion, lecturas, valores, color))

    if hay_datos:
        ax.set_facecolor("#ffffff")
        fig.patch.set_facecolor("#ffffff")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#c7ccc7")
        ax.spines["bottom"].set_color("#c7ccc7")
        ax.tick_params(colors="#6c757d", labelsize=7)
        ax.grid(axis="y", color="#e5e7e2", linewidth=0.6)
        ax.set_axisbelow(True)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
        ax.legend(fontsize=6, loc="upper right", frameon=False)
        fig.autofmt_xdate(rotation=25, ha="right")

        buffer = BytesIO()
        fig.tight_layout()
        fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        buffer.seek(0)

        story.append(Paragraph("Evolución comparada", ParagraphStyle("GT", parent=styles["Heading2"],
            fontName="Helvetica-Bold", fontSize=13, textColor=gris_oscuro, spaceAfter=8)))
        story.append(Image(buffer, width=doc.width, height=doc.width * (3.0 / 6.8)))
        story.append(Spacer(1, 20))

    # Tabla de estadísticas por sesión
    story.append(Paragraph("Estadísticas por sesión", ParagraphStyle("ST", parent=styles["Heading2"],
        fontName="Helvetica-Bold", fontSize=13, textColor=gris_oscuro, spaceAfter=10)))

    u = f" {device.unidad}" if device.unidad else ""
    encabezado = ["Sesión", f"Mín{u}", "Orden\nmín.", f"Máx{u}", "Orden\nmáx.", f"Media{u}", "Lecturas"]
    tabla_data = [encabezado]

    rojo = colors.HexColor("#c0392b")
    verde_ok = colors.HexColor("#27ae60")

    for sesion, lecturas, valores, _ in datasets:
        v_min = min(valores)
        v_max = max(valores)
        orden_min = next(i+1 for i, v in enumerate(valores) if v == v_min)
        orden_max = next(i+1 for i, v in enumerate(valores) if v == v_max)
        tabla_data.append([
            sesion.nombre,
            f"{v_min:.2f}",
            f"#{orden_min}",
            f"{v_max:.2f}",
            f"#{orden_max}",
            f"{sum(valores)/len(valores):.2f}",
            str(len(valores)),
        ])

    ancho_nombre = 4.5 * cm
    ancho_resto = (doc.width - ancho_nombre) / 6
    anchos = [ancho_nombre] + [ancho_resto] * 6

    tabla = Table(tabla_data, colWidths=anchos, repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), gris_oscuro),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8f6")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7e2")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    # Resaltar columnas de min (verde) y max (rojo) en las filas de datos
    for fila_idx in range(1, len(tabla_data)):
        estilo.append(("TEXTCOLOR", (1, fila_idx), (1, fila_idx), verde_ok))
        estilo.append(("FONTNAME", (1, fila_idx), (1, fila_idx), "Helvetica-Bold"))
        estilo.append(("TEXTCOLOR", (3, fila_idx), (3, fila_idx), rojo))
        estilo.append(("FONTNAME", (3, fila_idx), (3, fila_idx), "Helvetica-Bold"))

    tabla.setStyle(TableStyle(estilo))
    story.append(tabla)
    story.append(Spacer(1, 20))

    # Detalle de lecturas por sesión (tabla compacta)
    story.append(Paragraph("Detalle de lecturas por sesión", ParagraphStyle("DT", parent=styles["Heading2"],
        fontName="Helvetica-Bold", fontSize=13, textColor=gris_oscuro, spaceAfter=10)))

    for sesion, lecturas, valores, _ in datasets:
        story.append(Paragraph(sesion.nombre, ParagraphStyle("SN", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=10, textColor=gris_oscuro, spaceAfter=6, spaceBefore=12)))

        v_min = min(valores)
        v_max = max(valores)
        det_data = [["#", "Hora", f"Valor{u}"]]
        for i, l in enumerate(lecturas, start=1):
            det_data.append([
                str(i),
                timezone.localtime(l.timestamp).strftime("%d/%m %H:%M:%S"),
                f"{l.valor:.2f}",
            ])

        det = Table(det_data, colWidths=[1.5*cm, 5*cm, 4*cm], repeatRows=1)
        est_det = [
            ("BACKGROUND", (0, 0), (-1, 0), gris_oscuro),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8f6")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7e2")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, l in enumerate(lecturas, start=1):
            if l.valor == v_min:
                est_det.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eaf6ee")))
                est_det.append(("TEXTCOLOR", (2, i), (2, i), verde_ok))
                est_det.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
            elif l.valor == v_max:
                est_det.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fdecea")))
                est_det.append(("TEXTCOLOR", (2, i), (2, i), rojo))
                est_det.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))

        det.setStyle(TableStyle(est_det))
        story.append(det)

    doc.build(story)
    return response


@login_required
def device_create(request):
    """Agregar dispositivo: requiere estar logueado."""
    if request.method == "POST":
        form = DeviceForm(request.POST)
        if form.is_valid():
            device = form.save(commit=False)
            device.owner = request.user
            device.save()
            messages.success(
                request,
                "Dispositivo creado. Copiá el ID y la API Key para configurarlos en tu ESP32 (solo se muestran ahora).",
            )
            return redirect("devices:detail", pk=device.pk)
    else:
        form = DeviceForm()

    return render(request, "devices/device_form.html", {"form": form})


@login_required
def my_devices(request):
    devices = Device.objects.filter(owner=request.user)
    return render(request, "devices/my_devices.html", {"devices": devices})


@login_required
def archivar_lecturas(request, pk):
    """
    Copia las lecturas actuales de un dispositivo al historial
    (HistorialSensor) sin borrarlo ni interrumpir la medición.
    Útil para "guardar un corte" del historial antes de cambiar
    de tarea, sin tener que desvincular el sensor.
    """
    device = get_object_or_404(Device, pk=pk, owner=request.user)
    if request.method == "POST":
        cantidad = archivar_lecturas_de_device(device, solo_ultimos_dias=30)
        if cantidad > 0:
            messages.success(
                request,
                f"Se archivaron {cantidad} lecturas nuevas de '{device.nombre}' en el historial. "
                "El sensor sigue midiendo normalmente."
            )
        else:
            messages.info(
                request,
                f"Las lecturas recientes de '{device.nombre}' ya estaban archivadas — no hay nada nuevo que guardar."
            )
    return redirect("devices:my_devices")


@login_required
def device_edit(request, pk):
    """
    Permite corregir nombre, ubicación, tipo de sensor y etiquetas de
    un dispositivo ya vinculado. Solo el dueño puede editarlo.
    """
    device = get_object_or_404(Device, pk=pk, owner=request.user)

    if request.method == "POST":
        form = VincularDeviceForm(request.POST, instance=device)
        if form.is_valid():
            form.save()
            messages.success(request, f"'{device.nombre}' actualizado.")
            return redirect("devices:detail", pk=device.pk)
    else:
        form = VincularDeviceForm(instance=device)

    return render(request, "devices/device_edit.html", {"form": form, "device": device})


@login_required
def device_delete(request, pk):
    """
    Elimina un dispositivo. Solo el dueño puede hacerlo.

    Comportamiento normal: se manda un comando RESET al ESP32. Cuando el
    dispositivo confirma haberlo ejecutado (en ComandoEjecutadoView), recién
    ahí se borra de la base, así el ESP32 queda "limpio" y listo para
    vincularse de nuevo (en vez de quedar con una API Key que ya no sirve).

    Si el dispositivo está offline y nunca va a confirmar, se puede forzar
    el borrado inmediato desde el mismo formulario.
    """
    device = get_object_or_404(Device, pk=pk, owner=request.user)

    if request.method == "POST":
        nombre = device.nombre

        if request.POST.get("accion") == "forzar":
            archivar_lecturas_de_device(device)
            device.delete()
            messages.success(request, f"Dispositivo '{nombre}' eliminado. Sus mediciones quedaron en el historial.")
            return redirect("devices:my_devices")

        Comando.objects.create(device=device, accion="RESET")
        messages.success(
            request,
            f"Se envió la orden de reset a '{nombre}'. Se va a eliminar automáticamente "
            "en cuanto el dispositivo la reciba y confirme.",
        )
        return redirect("devices:my_devices")

    return render(request, "devices/device_confirm_delete.html", {"device": device})


@login_required
def solicitudes_vinculo(request):
    """
    Panel de 'emparejamiento': muestra los ESP32 que se están anunciando
    (prendidos, conectados a WiFi, esperando que alguien los vincule).
    """
    solicitudes = SolicitudVinculo.objects.filter(estado="pendiente").order_by("-creado_en")
    return render(request, "devices/solicitudes_vinculo.html", {"solicitudes": solicitudes})


@login_required
def vincular_dispositivo(request, solicitud_id):
    """
    Confirma la vinculación: crea el Device real, lo asocia a la
    solicitud, y a partir de ahí el ESP32 va a recibir la API Key
    la próxima vez que haga polling de estado.
    """
    solicitud = get_object_or_404(SolicitudVinculo, pk=solicitud_id, estado="pendiente")

    if request.method == "POST":
        form = VincularDeviceForm(request.POST)
        if form.is_valid():
            device = form.save(commit=False)
            device.owner = request.user
            device.save()

            solicitud.device = device
            solicitud.estado = "vinculado"
            solicitud.save(update_fields=["device", "estado", "actualizado_en"])

            messages.success(request, f"¡Dispositivo '{device.nombre}' vinculado con éxito!")
            return redirect("devices:detail", pk=device.pk)
    else:
        form = VincularDeviceForm(initial={"nombre": f"ESP32 {solicitud.codigo}"})

    return render(
        request,
        "devices/vincular_dispositivo.html",
        {"form": form, "solicitud": solicitud},
    )


@login_required
def descartar_solicitud(request, solicitud_id):
    """Borra una solicitud de vinculación pendiente que ya no sirve (duplicada, vieja, etc.)."""
    solicitud = get_object_or_404(SolicitudVinculo, pk=solicitud_id, estado="pendiente")

    if request.method == "POST":
        solicitud.delete()
        messages.success(request, "Solicitud descartada.")

    return redirect("devices:solicitudes_vinculo")


def descargar_sesion_pdf(request, pk, sesion_id):
    """
    Genera un PDF con todas las lecturas de UNA sesión de medición
    puntual (por ejemplo "Línea A"), sin importar cuántos días haya
    durado. Público, igual que el resto de los reportes de un dispositivo.
    """
    from datetime import datetime as dt, timedelta
    from io import BytesIO

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    from django.http import HttpResponse
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    device = get_object_or_404(Device, pk=pk)
    sesion = get_object_or_404(SesionMedicion, pk=sesion_id, device=device)

    lecturas = list(sesion.lecturas.order_by("timestamp"))

    response = HttpResponse(content_type="application/pdf")
    nombre_archivo = f"lumbre_{device.nombre.replace(' ', '_')}_{sesion.nombre.replace(' ', '_')}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{nombre_archivo}"'

    doc = SimpleDocTemplate(
        response, pagesize=letter,
        topMargin=1.5 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    verde = colors.HexColor("#2f9e5f")
    gris_oscuro = colors.HexColor("#10231a")
    gris = colors.HexColor("#6c757d")
    navy_fondo = colors.HexColor("#0b1114")

    header_style = ParagraphStyle(
        "Header", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=15, textColor=colors.white, leading=18,
    )
    header_text = (
        "Lumbre <font size='9' color='#8a94a3'>para</font> "
        "<font color='#ffffff'>COPAN</font><font color='#e8752c'>SEGUROS</font>"
    )
    header_table = Table([[Paragraph(header_text, header_style)]], colWidths=[doc.width])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), navy_fondo),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
    ]))

    subtitulo_style = ParagraphStyle(
        "Subtitulo", parent=styles["Normal"], fontName="Helvetica",
        fontSize=12, textColor=gris_oscuro, spaceAfter=4, spaceBefore=18,
    )
    fecha_style = ParagraphStyle(
        "FechaGrande", parent=styles["Normal"], fontName="Helvetica",
        fontSize=10, textColor=gris, spaceAfter=14,
    )

    inicio_local = timezone.localtime(sesion.inicio)
    fin_local = timezone.localtime(sesion.fin) if sesion.fin else None
    rango = f"{inicio_local.strftime('%d/%m/%Y %H:%M')} — "
    rango += fin_local.strftime('%d/%m/%Y %H:%M') if fin_local else "en curso"

    story = [
        header_table,
        Spacer(1, 0),
        Paragraph(f"Sesión de medición — {device.nombre}", subtitulo_style),
        Paragraph(f"{sesion.nombre} · {rango}", fecha_style),
        HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#e5e7e2"), spaceAfter=16),
    ]

    info_data = [
        ["Dispositivo:", device.nombre],
        ["Sesión:", sesion.nombre],
        ["Inicio:", inicio_local.strftime("%d/%m/%Y %H:%M:%S")],
        ["Fin:", fin_local.strftime("%d/%m/%Y %H:%M:%S") if fin_local else "En curso"],
        ["Cantidad de lecturas:", str(len(lecturas))],
    ]
    info_table = Table(info_data, colWidths=[4 * cm, 10 * cm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), gris_oscuro),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 16))

    if lecturas:
        valores = [l.valor for l in lecturas]
        stats_data = [
            ["Mínimo", "Máximo", "Promedio"],
            [f"{min(valores):.2f}", f"{max(valores):.2f}", f"{sum(valores)/len(valores):.2f}"],
        ]
        stats_table = Table(stats_data, colWidths=[4.6 * cm, 4.6 * cm, 4.6 * cm])
        stats_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), verde),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7e2")),
        ]))
        story.append(stats_table)
        story.append(Spacer(1, 24))

        # Gráfico (con el mismo muestreo que el resto de los reportes)
        def muestrear(lista_lecturas, max_puntos=150):
            lista_local = [(timezone.localtime(l.timestamp).replace(tzinfo=None), l.valor) for l in lista_lecturas]
            if len(lista_local) <= max_puntos:
                return lista_local
            inicio = lista_local[0][0]
            fin = lista_local[-1][0]
            duracion = (fin - inicio).total_seconds() or 1
            intervalo = duracion / max_puntos
            buckets = {}
            for ts, valor in lista_local:
                offset = (ts - inicio).total_seconds()
                indice = int(offset // intervalo)
                if indice not in buckets:
                    buckets[indice] = {"suma": 0.0, "cantidad": 0, "t_suma": 0.0}
                b = buckets[indice]
                b["suma"] += valor
                b["t_suma"] += offset
                b["cantidad"] += 1
            resultado = []
            for indice in sorted(buckets):
                b = buckets[indice]
                t_promedio = inicio + timedelta(seconds=b["t_suma"] / b["cantidad"])
                resultado.append((t_promedio, round(b["suma"] / b["cantidad"], 2)))
            return resultado

        puntos = muestrear(lecturas)
        horas = [p[0] for p in puntos]
        valores_grafico = [p[1] for p in puntos]

        fig, ax = plt.subplots(figsize=(6.8, 2.6), dpi=150)
        ax.plot(horas, valores_grafico, color="#2f9e5f", linewidth=1.6)
        ax.fill_between(horas, valores_grafico, min(valores_grafico), color="#2f9e5f", alpha=0.12)
        ax.set_facecolor("#ffffff")
        fig.patch.set_facecolor("#ffffff")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#c7ccc7")
        ax.spines["bottom"].set_color("#c7ccc7")
        ax.tick_params(colors="#6c757d", labelsize=8)
        ax.grid(axis="y", color="#e5e7e2", linewidth=0.6)
        ax.set_axisbelow(True)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
        fig.autofmt_xdate(rotation=25, ha="right")

        buffer = BytesIO()
        fig.tight_layout()
        fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        buffer.seek(0)

        grafico_titulo_style = ParagraphStyle(
            "GraficoTitulo", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, textColor=gris_oscuro, spaceAfter=8,
        )
        story.append(Paragraph("Evolución durante la sesión", grafico_titulo_style))
        story.append(Image(buffer, width=doc.width, height=doc.width * (2.6 / 6.8)))
        story.append(Spacer(1, 20))

        mediciones_titulo_style = ParagraphStyle(
            "MedicionesTitulo", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, textColor=gris_oscuro, spaceAfter=10,
        )
        story.append(Paragraph("Mediciones", mediciones_titulo_style))

        tabla_data = [["#", "Fecha y hora", "Valor"]]
        for i, l in enumerate(lecturas, start=1):
            tabla_data.append([
                str(i),
                timezone.localtime(l.timestamp).strftime("%d/%m %H:%M:%S"),
                f"{l.valor:.2f}",
            ])

        tabla = Table(tabla_data, colWidths=[2 * cm, 6 * cm, 6 * cm], repeatRows=1)
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), gris_oscuro),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8f6")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7e2")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tabla)
    else:
        story.append(Paragraph("Esta sesión todavía no tiene lecturas registradas.", styles["Normal"]))

    doc.build(story)
    return response


def descargar_lecturas_pdf(request, pk):
    """
    Genera un PDF con todas las lecturas de un dispositivo en un día
    específico. Público (igual que ver el detalle del dispositivo) -
    consistente con que los datos son compartidos entre usuarios.

    GET /dispositivos/<uuid:pk>/lecturas/pdf/?fecha=YYYY-MM-DD
    """
    from datetime import datetime as dt, timedelta
    from io import BytesIO

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    from django.http import HttpResponse
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    device = get_object_or_404(Device, pk=pk)

    fecha_str = request.GET.get("fecha")
    if fecha_str:
        try:
            fecha = dt.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            return HttpResponse("Formato de fecha inválido. Usá YYYY-MM-DD.", status=400)
    else:
        # Sin parámetro: por defecto, el día de hoy (en la zona horaria
        # configurada del proyecto, no en UTC del servidor).
        fecha = timezone.localtime(timezone.now()).date()
        fecha_str = fecha.strftime("%Y-%m-%d")

    lecturas = device.lecturas.filter(timestamp__date=fecha).order_by("timestamp")

    response = HttpResponse(content_type="application/pdf")
    nombre_archivo = f"lumbre_{device.nombre.replace(' ', '_')}_{fecha_str}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{nombre_archivo}"'

    doc = SimpleDocTemplate(
        response, pagesize=letter,
        topMargin=1.5 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    verde = colors.HexColor("#2f9e5f")
    gris_oscuro = colors.HexColor("#10231a")
    gris = colors.HexColor("#6c757d")
    navy_fondo = colors.HexColor("#0b1114")

    # -----------------------------------------------------------------
    # Encabezado tipo navbar: "Lumbre para COPAN SEGUROS"
    # -----------------------------------------------------------------
    header_style = ParagraphStyle(
        "Header", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=15, textColor=colors.white, leading=18,
    )
    header_text = (
        "Lumbre "
        "<font size='9' color='#8a94a3'>para</font> "
        "<font color='#ffffff'>COPAN</font>"
        "<font color='#e8752c'>SEGUROS</font>"
    )
    header_table = Table([[Paragraph(header_text, header_style)]], colWidths=[doc.width])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), navy_fondo),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
    ]))

    subtitulo_style = ParagraphStyle(
        "Subtitulo", parent=styles["Normal"], fontName="Helvetica",
        fontSize=12, textColor=gris_oscuro, spaceAfter=4, spaceBefore=18,
    )
    fecha_style = ParagraphStyle(
        "FechaGrande", parent=styles["Normal"], fontName="Helvetica",
        fontSize=10, textColor=gris, spaceAfter=14,
    )

    story = [
        header_table,
        Spacer(1, 0),
        Paragraph(f"Reporte de mediciones — {device.nombre}", subtitulo_style),
        Paragraph(f"{fecha.strftime('%d/%m/%Y')}", fecha_style),
        HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#e5e7e2"), spaceAfter=16),
    ]

    info_data = [
        ["Dispositivo:", device.nombre],
        ["Ubicación:", device.ubicacion or "—"],
        ["Fecha:", fecha.strftime("%d/%m/%Y")],
        ["Cantidad de lecturas:", str(lecturas.count())],
    ]
    info_table = Table(info_data, colWidths=[4 * cm, 10 * cm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), gris_oscuro),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 16))

    if lecturas.exists():
        lista_lecturas = list(lecturas)
        valores = [l.valor for l in lista_lecturas]

        valor_min = min(valores)
        valor_max = max(valores)

        # Buscamos la primera lectura que coincide con el mínimo/máximo,
        # para poder mostrar en qué momento del día ocurrió.
        detalle_min = ""
        detalle_max = ""
        for i, l in enumerate(lista_lecturas, start=1):
            if l.valor == valor_min and not detalle_min:
                hora_min = timezone.localtime(l.timestamp).strftime("%H:%M:%S")
                detalle_min = f"Medición #{i} — {hora_min}"
            if l.valor == valor_max and not detalle_max:
                hora_max = timezone.localtime(l.timestamp).strftime("%H:%M:%S")
                detalle_max = f"Medición #{i} — {hora_max}"

        detalle_style = ParagraphStyle(
            "DetalleStats", parent=styles["Normal"], fontName="Helvetica",
            fontSize=8, textColor=gris, alignment=1,  # 1 = centrado
        )

        stats_data = [
            ["Mínimo", "Máximo", "Promedio"],
            [f"{valor_min:.2f}", f"{valor_max:.2f}", f"{sum(valores)/len(valores):.2f}"],
            [Paragraph(detalle_min, detalle_style), Paragraph(detalle_max, detalle_style), ""],
        ]
        stats_table = Table(stats_data, colWidths=[4.6 * cm, 4.6 * cm, 4.6 * cm])
        stats_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), verde),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 1), 11),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
            ("TOPPADDING", (0, 1), (-1, 1), 8),
            ("BOTTOMPADDING", (0, 2), (-1, 2), 8),
            ("TOPPADDING", (0, 2), (-1, 2), 2),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7e2")),
        ]))
        story.append(stats_table)
        story.append(Spacer(1, 24))

        # -------------------------------------------------------------
        # Gráfico de líneas de las mediciones del día
        #
        # Usamos el mismo muestreo (promediado en ~150 "cajones" de
        # tiempo) que aplica el gráfico de la web - así el PDF muestra
        # EXACTAMENTE la misma curva que se ve en pantalla en vez de
        # graficar cada lectura cruda (que con mucha densidad se ve
        # como un bloque sólido en vez de una curva legible).
        # -------------------------------------------------------------
        def muestrear(lista_lecturas, max_puntos=150):
            # Convertimos cada timestamp a la hora local (Argentina) antes
            # de graficar - las fechas se guardan en UTC en la base. Además,
            # le sacamos la info de zona horaria (.replace(tzinfo=None))
            # porque matplotlib, si detecta que el datetime sigue "aware",
            # lo vuelve a convertir a UTC internamente para graficar,
            # deshaciendo la conversión que acabamos de hacer.
            lista_local = [
                (timezone.localtime(l.timestamp).replace(tzinfo=None), l.valor)
                for l in lista_lecturas
            ]

            if len(lista_local) <= max_puntos:
                return lista_local

            inicio = lista_local[0][0]
            fin = lista_local[-1][0]
            duracion = (fin - inicio).total_seconds() or 1
            intervalo = duracion / max_puntos

            buckets = {}
            for ts, valor in lista_local:
                offset = (ts - inicio).total_seconds()
                indice = int(offset // intervalo)
                if indice not in buckets:
                    buckets[indice] = {"suma": 0.0, "cantidad": 0, "t_suma": 0.0}
                b = buckets[indice]
                b["suma"] += valor
                b["t_suma"] += offset
                b["cantidad"] += 1

            resultado = []
            for indice in sorted(buckets):
                b = buckets[indice]
                t_promedio = inicio + timedelta(seconds=b["t_suma"] / b["cantidad"])
                v_promedio = round(b["suma"] / b["cantidad"], 2)
                resultado.append((t_promedio, v_promedio))
            return resultado

        puntos_muestreados = muestrear(list(lecturas))
        horas = [p[0] for p in puntos_muestreados]
        valores_grafico = [p[1] for p in puntos_muestreados]

        fig, ax = plt.subplots(figsize=(6.8, 2.6), dpi=150)
        ax.plot(horas, valores_grafico, color="#2f9e5f", linewidth=1.6)
        ax.fill_between(horas, valores_grafico, min(valores_grafico), color="#2f9e5f", alpha=0.12)

        ax.set_facecolor("#ffffff")
        fig.patch.set_facecolor("#ffffff")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#c7ccc7")
        ax.spines["bottom"].set_color("#c7ccc7")
        ax.tick_params(colors="#6c757d", labelsize=8)
        ax.grid(axis="y", color="#e5e7e2", linewidth=0.6)
        ax.set_axisbelow(True)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        fig.autofmt_xdate(rotation=0, ha="center")

        buffer = BytesIO()
        fig.tight_layout()
        fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        buffer.seek(0)

        grafico_titulo_style = ParagraphStyle(
            "GraficoTitulo", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, textColor=gris_oscuro, spaceAfter=8,
        )
        story.append(Paragraph("Evolución en el día", grafico_titulo_style))
        story.append(Image(buffer, width=doc.width, height=doc.width * (2.6 / 6.8)))
        story.append(Spacer(1, 20))

        mediciones_titulo_style = ParagraphStyle(
            "MedicionesTitulo", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, textColor=gris_oscuro, spaceAfter=10,
        )
        story.append(Paragraph("Mediciones del día", mediciones_titulo_style))

        tabla_data = [["#", "Hora", "Valor"]]
        fila_max = None
        fila_min = None
        for i, l in enumerate(lecturas, start=1):
            tabla_data.append([str(i), timezone.localtime(l.timestamp).strftime("%H:%M:%S"), f"{l.valor:.2f}"])
            if l.valor == max(valores) and fila_max is None:
                fila_max = i  # +1 por la fila de encabezado, ya contemplado en TableStyle
            if l.valor == min(valores) and fila_min is None:
                fila_min = i

        rojo = colors.HexColor("#c0392b")

        tabla = Table(tabla_data, colWidths=[2 * cm, 6 * cm, 6 * cm], repeatRows=1)
        estilo_tabla = [
            ("BACKGROUND", (0, 0), (-1, 0), gris_oscuro),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("TEXTCOLOR", (0, 1), (0, -1), gris),
            ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (2, 1), (2, -1), gris_oscuro),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8f6")]),
            ("LINEBELOW", (0, 0), (-1, 0), 1, verde),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#e5e7e2")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]

        # Resaltamos la fila del valor máximo (rojo) y del mínimo (verde),
        # con fondo suave + texto en negrita del color correspondiente.
        if fila_max is not None:
            estilo_tabla.append(("BACKGROUND", (0, fila_max), (-1, fila_max), colors.HexColor("#fdecea")))
            estilo_tabla.append(("TEXTCOLOR", (2, fila_max), (2, fila_max), rojo))
            estilo_tabla.append(("FONTNAME", (0, fila_max), (-1, fila_max), "Helvetica-Bold"))
        if fila_min is not None:
            estilo_tabla.append(("BACKGROUND", (0, fila_min), (-1, fila_min), colors.HexColor("#eaf6ee")))
            estilo_tabla.append(("TEXTCOLOR", (2, fila_min), (2, fila_min), verde))
            estilo_tabla.append(("FONTNAME", (0, fila_min), (-1, fila_min), "Helvetica-Bold"))

        tabla.setStyle(TableStyle(estilo_tabla))
        story.append(tabla)
    else:
        story.append(Paragraph("No hay lecturas registradas para este día.", styles["Normal"]))

    doc.build(story)
    return response
