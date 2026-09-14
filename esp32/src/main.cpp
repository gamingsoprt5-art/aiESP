/*
 * AI Smart Glasses — ESP32 firmware (starting point)
 * ----------------------------------------------------
 * What this file DOES implement:
 *   - Wi-Fi connection
 *   - Anonymous device registration against POST /api/devices/register,
 *     with the resulting device token persisted in NVS (Preferences)
 *     so it survives reboots (re-flashing does NOT lose the identity,
 *     as long as INSTALLATION_ID is also persisted rather than regenerated).
 *   - Sending a text query to POST /api/chat and printing the AI's reply
 *     to Serial.
 *
 * What this file intentionally does NOT implement (hardware-specific,
 * and out of scope for what can be verified without physical hardware):
 *   - Microphone capture + speech-to-text on-device. Two realistic paths:
 *       (a) capture raw audio over I2S and stream it to a server-side STT
 *           endpoint you add, or
 *       (b) use a library/module with on-device STT.
 *   - Speaker playback / text-to-speech of the AI's reply. Similarly,
 *     either stream server-generated TTS audio, or use an on-device TTS
 *     module.
 *   - Button/gesture wake handling, battery management, display driver
 *     (if your glasses have a HUD).
 *
 * Treat this as the network + API integration layer; wire your specific
 * audio hardware's capture/playback callbacks into `onWakeWordOrButton()`
 * and `speakReply()` below.
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>

#include "config.h"

Preferences prefs;
String installationId;
String deviceToken;
String conversationId = "";

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Menghubungkan ke Wi-Fi");
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("Wi-Fi terhubung: " + WiFi.localIP().toString());
  } else {
    Serial.println("Gagal terhubung ke Wi-Fi — akan dicoba lagi di loop().");
  }
}

String loadOrCreateInstallationId() {
  String id = prefs.getString("installation_id", "");
  if (id.length() == 0) {
    // Derive a stable id from the chip's MAC so re-flashing keeps the same identity.
    uint64_t mac = ESP.getEfuseMac();
    char buf[32];
    snprintf(buf, sizeof(buf), "%s%012llx", INSTALLATION_ID_PREFIX, mac);
    id = String(buf);
    prefs.putString("installation_id", id);
  }
  return id;
}

bool registerDevice() {
  deviceToken = prefs.getString("device_token", "");
  if (deviceToken.length() > 0) {
    Serial.println("Token perangkat sudah ada di NVS, lewati registrasi.");
    return true;
  }

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.begin(String(API_BASE_URL) + "/api/devices/register");
  http.addHeader("Content-Type", "application/json");

  JsonDocument body;
  body["installation_id"] = installationId;
  body["device_name"] = "ESP32 Smart Glasses";
  String payload;
  serializeJson(body, payload);

  int status = http.POST(payload);
  if (status != 200) {
    Serial.printf("Registrasi perangkat gagal, HTTP %d\n", status);
    http.end();
    return false;
  }

  JsonDocument res;
  deserializeJson(res, http.getString());
  deviceToken = res["device_token"].as<String>();
  prefs.putString("device_token", deviceToken);
  http.end();
  Serial.println("Perangkat terdaftar, token disimpan.");
  return true;
}

// Called with the recognized text once your STT pipeline produces one.
// For now, wire this manually (e.g. over Serial for testing) until
// on-device or streaming STT is integrated.
String sendChatText(const String &text, const String &outputMode) {
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.begin(String(API_BASE_URL) + "/api/chat");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", "Device " + deviceToken);

  JsonDocument body;
  body["client_message_id"] = installationId + "-" + String(millis());
  if (conversationId.length() > 0) body["conversation_id"] = conversationId;
  body["text"] = text;
  body["output_mode"] = outputMode;   // "voice" for spoken replies
  body["ai_mode"] = "online";         // ESP32 typically relies on cloud AI (no local Ollama on-device)
  String payload;
  serializeJson(body, payload);

  int status = http.POST(payload);
  if (status != 200) {
    Serial.printf("Permintaan chat gagal, HTTP %d: %s\n", status, http.getString().c_str());
    http.end();
    return "";
  }

  JsonDocument res;
  deserializeJson(res, http.getString());
  conversationId = res["conversation_id"].as<String>();
  String reply = res["assistant_message"]["content"].as<String>();
  http.end();
  return reply;
}

// TODO: wire this to your speaker/TTS hardware.
void speakReply(const String &text) {
  Serial.println("[AI] " + text);
  // e.g. stream to an I2S amp via an on-device TTS engine, or request
  // pre-synthesized audio from a server endpoint you add.
}

// TODO: wire this to your mic/button/wake-word hardware. As a placeholder,
// it reads a line from Serial so you can test the network layer today.
void onWakeWordOrButton() {
  if (!Serial.available()) return;
  String text = Serial.readStringUntil('\n');
  text.trim();
  if (text.length() == 0) return;

  Serial.println("Anda: " + text);
  String reply = sendChatText(text, "voice");
  if (reply.length() > 0) speakReply(reply);
}

void setup() {
  Serial.begin(115200);
  delay(300);

  prefs.begin("smartglasses", false);
  installationId = loadOrCreateInstallationId();
  Serial.println("Installation ID: " + installationId);

  connectWifi();
  if (WiFi.status() == WL_CONNECTED) {
    registerDevice();
  }

  Serial.println("Siap. Ketik pesan di Serial Monitor untuk menguji /api/chat.");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
    delay(1000);
    return;
  }
  if (deviceToken.length() == 0) {
    registerDevice();
    delay(1000);
    return;
  }

  onWakeWordOrButton();
  delay(50);
}
