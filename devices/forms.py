from django import forms

from .models import Comando, Device


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["nombre", "ubicacion", "descripcion"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "input", "placeholder": "Ej: Bobina Portón Principal"}),
            "ubicacion": forms.TextInput(attrs={"class": "input", "placeholder": "Ej: Entrada, Taller, etc."}),
            "descripcion": forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Opcional"}),
        }


class ComandoForm(forms.ModelForm):
    class Meta:
        model = Comando
        fields = ["accion", "parametro"]
        widgets = {
            "accion": forms.TextInput(attrs={"class": "input", "placeholder": "Ej: ON, OFF, RESET"}),
            "parametro": forms.TextInput(attrs={"class": "input", "placeholder": "Opcional"}),
        }
