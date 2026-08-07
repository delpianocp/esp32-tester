import json

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .account_forms import RegistroForm
from .forms import ComandoForm, DeviceForm, VincularDeviceForm
from .models import Comando, Device, SolicitudVinculo


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


def device_list(request):
    """Home: cualquier usuario (logueado o no) puede ver todos los dispositivos."""
    devices = Device.objects.select_related("owner").all()
    return render(request, "devices/device_list.html", {"devices": devices})


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
    }
    return render(request, "devices/device_detail.html", context)


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
            device.delete()
            messages.success(request, f"Dispositivo '{nombre}' eliminado.")
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


def descargar_lecturas_pdf(request, pk):
    """
    Genera un PDF con todas las lecturas de un dispositivo en un día
    específico. Público (igual que ver el detalle del dispositivo) -
    consistente con que los datos son compartidos entre usuarios.

    GET /dispositivos/<uuid:pk>/lecturas/pdf/?fecha=YYYY-MM-DD
    """
    from datetime import datetime as dt

    from django.http import HttpResponse
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    device = get_object_or_404(Device, pk=pk)

    fecha_str = request.GET.get("fecha")
    if not fecha_str:
        return HttpResponse("Falta el parámetro 'fecha' (YYYY-MM-DD).", status=400)

    try:
        fecha = dt.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        return HttpResponse("Formato de fecha inválido. Usá YYYY-MM-DD.", status=400)

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
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
            ("TOPPADDING", (0, 1), (-1, 1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7e2")),
        ]))
        story.append(stats_table)
        story.append(Spacer(1, 24))

        mediciones_titulo_style = ParagraphStyle(
            "MedicionesTitulo", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, textColor=gris_oscuro, spaceAfter=10,
        )
        story.append(Paragraph("Mediciones del día", mediciones_titulo_style))

        tabla_data = [["#", "Hora", "Valor"]]
        for i, l in enumerate(lecturas, start=1):
            tabla_data.append([str(i), l.timestamp.strftime("%H:%M:%S"), f"{l.valor:.2f}"])

        tabla = Table(tabla_data, colWidths=[2 * cm, 6 * cm, 6 * cm], repeatRows=1)
        tabla.setStyle(TableStyle([
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
        ]))
        story.append(tabla)
    else:
        story.append(Paragraph("No hay lecturas registradas para este día.", styles["Normal"]))

    doc.build(story)
    return response
