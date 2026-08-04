from django import forms

from .models import Comando, Device


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["nombre", "ubicacion", "descripcion"]
        widgets = {
            "nombre": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Ej: Bobina Portón Principal"
            }),
            "ubicacion": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Ej: Entrada, Taller, etc."
            }),
            "descripcion": forms.Textarea(attrs={
                "class": "form-control", "rows": 3, "placeholder": "Opcional"
            }),
        }


class VincularDeviceForm(forms.ModelForm):
    """Mismo form que DeviceForm, pero usado en el flujo de vinculación/emparejamiento."""

    class Meta:
        model = Device
        fields = ["nombre", "ubicacion", "descripcion"]
        widgets = {
            "nombre": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Ej: Bobina Portón Principal"
            }),
            "ubicacion": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Ej: Entrada, Taller, etc."
            }),
            "descripcion": forms.Textarea(attrs={
                "class": "form-control", "rows": 3, "placeholder": "Opcional"
            }),
        }


class ComandoForm(forms.ModelForm):
    class Meta:
        model = Comando
        fields = ["accion", "parametro"]
        widgets = {
            "accion": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Ej: ON, OFF, RESET"
            }),
            "parametro": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Opcional"
            }),
        }
