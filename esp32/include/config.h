#pragma once

// ---- Wi-Fi ----
#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"

// ---- Backend ----
// Point this at your deployed server (Replit URL, or your own host).
// Must be reachable from the glasses' Wi-Fi network.
#define API_BASE_URL    "https://your-server.example.com"

// A stable per-device identifier. In production, generate this once
// (e.g. from the ESP32's efuse MAC) and persist it in NVS/Preferences
// instead of hard-coding it, so re-flashing doesn't create a new device.
#define INSTALLATION_ID_PREFIX  "esp32-"

#define HTTP_TIMEOUT_MS  20000
