#pragma once

// Tat brownout detector neu nguon cap 5V yeu gay sut ap luc khoi dong/phat Wi-Fi
// #define DISABLE_BROWNOUT

// Thong tin ket noi Wi-Fi ngoai (Station Mode - STA)
#define WIFI_SSID "YOUR_PHONE_HOTSPOT"
#define WIFI_PASSWORD "YOUR_HOTSPOT_PASSWORD"
#define WIFI_CONNECT_TIMEOUT_MS 15000

// Thong tin diem phat song Wi-Fi tu phat (Access Point - AP)
#define AP_SSID "ESP32_DIEM_DANH"
#define AP_PASSWORD "12345678"

// Hostname mDNS (esp32cam.local) va cong suat phat song Wi-Fi
#define CAMERA_HOSTNAME "esp32cam"
#define WIFI_TX_POWER_MAX 1 // 1 = dat WIFI_POWER_19_5dBm; 0 = de mac dinh, dung khi nguon yeu bi reset

// Cac cau hinh cu giu lai de tuong thich neu cho khac can dung
#define SERVER_URL "http://192.168.1.10:8000"
#define DEVICE_ID "esp32-cam-01"
#define DEVICE_TOKEN "COPY_DEVICE_TOKEN_FROM_BACKEND_ENV"
#define FRAME_INTERVAL_MS 800
