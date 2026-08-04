from rest_framework import serializers

from devices.models import Comando, Lectura


class LecturaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lectura
        fields = ["id", "valor", "metadata", "timestamp"]
        read_only_fields = ["id", "timestamp"]


class ComandoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comando
        fields = ["id", "accion", "parametro", "estado", "creado_en"]
        read_only_fields = fields
