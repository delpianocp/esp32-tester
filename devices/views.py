from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .account_forms import RegistroForm
from .forms import ComandoForm, DeviceForm
from .models import Comando, Device


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

    context = {
        "device": device,
        "lecturas": lecturas,
        "comandos": comandos,
        "puede_controlar": puede_controlar,
        "comando_form": comando_form,
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
