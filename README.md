# ESP32 Monitor — Django

Plataforma web para registrar dispositivos ESP32 (con bobina como sensor), recibir sus lecturas y enviarles comandos.

## Stack

- Django 6 + Django REST Framework (API para el ESP32)
- SQLite en desarrollo / PostgreSQL en producción (Railway)
- Whitenoise para archivos estáticos
- Despliegue: Railway, conectado a GitHub

## Funcionalidad

- Cualquier visitante puede ver la lista de dispositivos y sus lecturas (público).
- Para **agregar** un dispositivo hace falta estar logueado (registro simple con usuario/contraseña).
- Al crear un dispositivo se genera automáticamente un **ID** y una **API Key** únicos.
- El ESP32 usa esos datos para autenticarse contra la API y mandar lecturas.
- El dueño del dispositivo tiene un panel para enviarle comandos (interactuar con el ESP32), que el propio dispositivo va a buscar haciendo polling.

## Desarrollo local

```bash
pip install -r requirements.txt
cp .env.example .env          # ajustar SECRET_KEY si querés
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abrir http://localhost:8000

## Variables de entorno

Ver `.env.example`. En desarrollo, si `DATABASE_URL` está vacío, usa SQLite automáticamente.

## Despliegue en Railway

1. Crear un proyecto nuevo en Railway y conectarlo a este repo de GitHub.
2. Agregar un plugin de **PostgreSQL** (Railway inyecta `DATABASE_URL` solo).
3. Configurar variables de entorno en Railway:
   - `SECRET_KEY` (generar una nueva, distinta a la de desarrollo)
   - `DEBUG=False`
   - `ALLOWED_HOSTS` (opcional, se agrega automáticamente el dominio de Railway)
4. Railway va a correr `release: python manage.py migrate` y luego `web: gunicorn config.wsgi` (ver `Procfile`).
5. Colectar estáticos: agregar a build command `python manage.py collectstatic --noinput` (o configurarlo como paso de build en Railway).

## API para el ESP32

### Enviar una lectura
```
POST /api/lecturas/
Header: Authorization: Api-Key <api_key_del_dispositivo>
Body (JSON): {"valor": 123.45, "metadata": {"opcional": true}}
```

### Consultar comandos pendientes (polling)
```
GET /api/comandos/pendientes/
Header: Authorization: Api-Key <api_key_del_dispositivo>
```

### Confirmar que un comando se ejecutó
```
POST /api/comandos/<id>/ejecutado/
Header: Authorization: Api-Key <api_key_del_dispositivo>
```

Ver `esp32_example/esp32_example.ino` para el firmware de referencia.

## Estructura

```
config/         # settings, urls raíz
devices/        # modelos, vistas web, templates de la plataforma
api/            # endpoints REST que consume el ESP32
templates/      # templates HTML
static/         # CSS
```
