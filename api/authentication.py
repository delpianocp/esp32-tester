from rest_framework import authentication, exceptions

from devices.models import Device


class DeviceApiKeyAuthentication(authentication.BaseAuthentication):
    """
    El ESP32 se autentica mandando el header:
    Authorization: Api-Key <api_key_del_dispositivo>
    """

    keyword = "Api-Key"

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith(self.keyword + " "):
            return None

        key = auth_header[len(self.keyword) + 1:].strip()
        try:
            device = Device.objects.get(api_key=key, activo=True)
        except Device.DoesNotExist:
            raise exceptions.AuthenticationFailed("API key inválida o dispositivo inactivo.")

        return (device, None)
