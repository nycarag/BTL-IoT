#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "config.h"

// Compatible with CameraWebServer: port 80 (/capture, /status) and port 81 (/stream).
// The laptop bridge pulls /capture or streams MJPEG. AI decisions stay on laptop.
static httpd_handle_t captureServer = nullptr;
static httpd_handle_t streamServer = nullptr;

static esp_err_t captureHandler(httpd_req_t *request) {
  camera_fb_t *frame = esp_camera_fb_get();
  if (!frame) return httpd_resp_send_500(request);
  httpd_resp_set_type(request, "image/jpeg");
  httpd_resp_set_hdr(request, "Content-Disposition", "inline; filename=capture.jpg");
  httpd_resp_set_hdr(request, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store, private");
  esp_err_t result = httpd_resp_send(request, (const char *)frame->buf, frame->len);
  esp_camera_fb_return(frame);
  return result;
}

static esp_err_t statusHandler(httpd_req_t *request) {
  static char json[128];
  sensor_t *s = esp_camera_sensor_get();
  if (!s) return httpd_resp_send_500(request);
  snprintf(json, sizeof(json),
           "{\"framesize\":%u,\"quality\":%u,\"psram\":%s}",
           s->status.framesize, s->status.quality, psramFound() ? "true" : "false");
  httpd_resp_set_type(request, "application/json");
  httpd_resp_set_hdr(request, "Access-Control-Allow-Origin", "*");
  return httpd_resp_send(request, json, strlen(json));
}

static esp_err_t streamHandler(httpd_req_t *request) {
  camera_fb_t *frame = NULL;
  esp_err_t result = httpd_resp_set_type(request, "multipart/x-mixed-replace;boundary=frame");
  if (result != ESP_OK) return result;
  httpd_resp_set_hdr(request, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(request, "X-Framerate", "30");

  char header[96];
  while (true) {
    frame = esp_camera_fb_get();
    if (!frame) {
      result = ESP_FAIL;
    } else {
      int length = snprintf(header, sizeof(header), "\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", (unsigned)frame->len);
      result = httpd_resp_send_chunk(request, header, length);
      if (result == ESP_OK) {
        result = httpd_resp_send_chunk(request, (const char *)frame->buf, frame->len);
      }
      esp_camera_fb_return(frame);
      frame = NULL;
    }
    if (result != ESP_OK) {
      break;
    }
  }
  return result;
}

void setup() {
  Serial.begin(115200);

#ifdef DISABLE_BROWNOUT
  // Chi tat brownout detector khi nguon 5V bi sut ap luc phat song; khuyen nghi nguon 5V/2A on dinh.
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
#endif

  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = 5; config.pin_d1 = 18; config.pin_d2 = 19; config.pin_d3 = 21;
  config.pin_d4 = 36; config.pin_d5 = 39; config.pin_d6 = 34; config.pin_d7 = 35;
  config.pin_xclk = 0; config.pin_pclk = 22; config.pin_vsync = 25; config.pin_href = 23;
  config.pin_sccb_sda = 26; config.pin_sccb_scl = 27;
  config.pin_pwdn = 32; config.pin_reset = -1;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;

  if (psramFound()) {
    config.frame_size = FRAMESIZE_CIF;
    config.jpeg_quality = 12;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera initialization failed");
    return;
  }

  WiFi.mode(WIFI_AP);
  IPAddress address(192, 168, 4, 1);
  if (!WiFi.softAPConfig(address, address, IPAddress(255, 255, 255, 0)) ||
      !WiFi.softAP(AP_SSID, AP_PASSWORD)) {
    Serial.println("SoftAP initialization failed; check password length >= 8");
    return;
  }

  // 1. Server tren Port 80: phuc vu /capture va /status
  httpd_config_t serverConfig = HTTPD_DEFAULT_CONFIG();
  serverConfig.server_port = 80;
  serverConfig.ctrl_port = 32768;

  httpd_uri_t capture = {};
  capture.uri = "/capture"; capture.method = HTTP_GET; capture.handler = captureHandler;
  httpd_uri_t status = {};
  status.uri = "/status"; status.method = HTTP_GET; status.handler = statusHandler;

  if (httpd_start(&captureServer, &serverConfig) == ESP_OK) {
    httpd_register_uri_handler(captureServer, &capture);
    httpd_register_uri_handler(captureServer, &status);
  }

  // 2. Server tren Port 81: tach rieng chuyen phuc vu /stream MJPEG
  serverConfig.server_port = 81;
  serverConfig.ctrl_port = 32769;
  httpd_uri_t stream = {};
  stream.uri = "/stream"; stream.method = HTTP_GET; stream.handler = streamHandler;
  if (httpd_start(&streamServer, &serverConfig) == ESP_OK) {
    httpd_register_uri_handler(streamServer, &stream);
  }

  Serial.printf("Wi-Fi: %s\nCapture: http://192.168.4.1/capture\nStatus:  http://192.168.4.1/status\nStream:  http://192.168.4.1:81/stream\n", AP_SSID);
}

void loop() {
  delay(1000);
}
