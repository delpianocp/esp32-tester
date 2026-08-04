/*
  ESP32 - Ejemplo de integración con la plataforma Django
  --------------------------------------------------------
  - Lee un valor analógico de la bobina (ajustar el pin/lógica según el sensor real).
  - Envía la lectura por HTTP POST a /api/lecturas/
  - Consulta periódicamente si hay comandos pendientes en /api/comandos/pendientes/

  Librerías necesarias (Arduino IDE / PlatformIO):
    - WiFi.h        (incluida en el core de ESP32)
    - HTTPClient.h  (incluida en el core de ESP32)
    - ArduinoJson   (instalar desde el Library Manager)
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ---------- CONFIGURACIÓN: completar con tus datos ----------
const char* WIFI_SSID     = "TU_WIFI";
const char* WIFI_PASSWORD = "TU_PASSWORD";

// Reemplazar por la URL real de tu app en Railway (o localhost:8000 en desarrollo,
// usando la IP de tu PC en la red local, no "localhost").
const char* BASE_URL = "https://tuapp.up.railway.app";

// Estos dos valores se obtienen del panel "Mis dispositivos" en la web,
// al hacer click en "Ver credenciales" del dispositivo que creaste.
const char* API_KEY = "PEGAR_AQUI_LA_API_KEY_DEL_DISPOSITIVO";

const int PIN_BOBINA = 34;       // pin analógico donde está conectada la bobina
const unsigned long INTERVALO_LECTURA_MS = 5000;   // cada cuánto manda una lectura
const unsigned long INTERVALO_COMANDOS_MS = 3000;  // cada cuánto pregunta por comandos

unsigned long ultimaLectura = 0;
unsigned long ultimoPollComandos = 0;

void conectarWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Conectando a WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println("\nConectado. IP: " + WiFi.localIP().toString());
}

void enviarLectura(float valor) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(String(BASE_URL) + "/api/lecturas/");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Api-Key ") + API_KEY);

  StaticJsonDocument<128> doc;
  doc["valor"] = valor;
  String body;
  serializeJson(doc, body);

  int codigo = http.POST(body);
  Serial.printf("POST lectura (%.2f) -> HTTP %d\n", valor, codigo);
  http.end();
}

void consultarComandos() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(String(BASE_URL) + "/api/comandos/pendientes/");
  http.addHeader("Authorization", String("Api-Key ") + API_KEY);

  int codigo = http.GET();
  if (codigo == 200) {
    String respuesta = http.getString();
    StaticJsonDocument<1024> doc;
    deserializeJson(doc, respuesta);

    for (JsonObject comando : doc.as<JsonArray>()) {
      const char* accion = comando["accion"];
      const char* id = comando["id"];
      Serial.printf("Comando recibido: %s\n", accion);

      // Acá va la lógica real según la acción, por ejemplo:
      if (strcmp(accion, "ON") == 0) {
        // digitalWrite(PIN_RELE, HIGH);
      } else if (strcmp(accion, "OFF") == 0) {
        // digitalWrite(PIN_RELE, LOW);
      }

      // Opcional: confirmar ejecución
      // confirmarEjecucion(comando["id"]);
    }
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BOBINA, INPUT);
  conectarWiFi();
}

void loop() {
  unsigned long ahora = millis();

  if (ahora - ultimaLectura >= INTERVALO_LECTURA_MS) {
    ultimaLectura = ahora;
    int lecturaCruda = analogRead(PIN_BOBINA);
    float valor = lecturaCruda * (3.3 / 4095.0); // ejemplo: convertir a voltaje
    enviarLectura(valor);
  }

  if (ahora - ultimoPollComandos >= INTERVALO_COMANDOS_MS) {
    ultimoPollComandos = ahora;
    consultarComandos();
  }
}
