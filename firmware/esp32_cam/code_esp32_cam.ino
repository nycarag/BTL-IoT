#include "esp_camera.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <esp_wifi.h>
#include "esp_http_server.h"
#include "soc/soc.h"             // Thu vien quan ly nguon
#include "soc/rtc_cntl_reg.h"    // Thu vien tat brownout (chong sap nguon)
#include "config.h"

#ifndef WIFI_SSID
#define WIFI_SSID "YOUR_PHONE_HOTSPOT"
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "YOUR_HOTSPOT_PASSWORD"
#endif

#ifndef WIFI_CONNECT_TIMEOUT_MS
#define WIFI_CONNECT_TIMEOUT_MS 15000
#endif

#ifndef AP_SSID
#define AP_SSID "ESP32_DIEM_DANH"
#endif

#ifndef AP_PASSWORD
#define AP_PASSWORD "12345678"
#endif

#ifndef CAMERA_HOSTNAME
#define CAMERA_HOSTNAME "esp32cam"
#endif

#ifndef WIFI_TX_POWER_MAX
#define WIFI_TX_POWER_MAX 1
#endif

static bool is_sta_mode = false;
static volatile uint32_t stream_frame_count = 0;
static uint32_t stream_fps = 0;

// ========================================================
// 2. CAU HINH CHAN CAMERA AI-THINKER ESP32-CAM
// ========================================================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#define LED_BUILTIN_RED   33
#define FLASH_GPIO_NUM     4

static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=frame_boundary";
static const char* _STREAM_BOUNDARY = "\r\n--frame_boundary\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

httpd_handle_t camera_httpd = NULL;
httpd_handle_t stream_httpd = NULL;

// 1. XU LY STREAM VIDEO MJPEG LIEN TUC
static esp_err_t stream_handler(httpd_req_t *req) {
    camera_fb_t * fb = NULL;
    esp_err_t res = ESP_OK;
    size_t _jpg_buf_len = 0;
    uint8_t * _jpg_buf = NULL;
    char part_buf[64];

    res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
    if(res != ESP_OK) return res;

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_set_hdr(req, "X-Framerate", "30");

    while(true) {
        fb = esp_camera_fb_get();
        if (!fb) {
            res = ESP_FAIL;
        } else {
            _jpg_buf_len = fb->len;
            _jpg_buf = fb->buf;
        }
        if(res == ESP_OK) {
            size_t hlen = snprintf(part_buf, 64, _STREAM_PART, _jpg_buf_len);
            res = httpd_resp_send_chunk(req, part_buf, hlen);
        }
        if(res == ESP_OK) {
            res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
        }
        if(res == ESP_OK) {
            res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
        }
        if(fb) {
            esp_camera_fb_return(fb);
            fb = NULL;
            _jpg_buf = NULL;
        } else if(res == ESP_OK) {
            res = ESP_FAIL;
        }
        // Neu client dong ket noi hoac gui chunk loi -> THOAT NGAY lap tuc
        if(res != ESP_OK) {
            break;
        }
        stream_frame_count++;
    }
    return res;
}

// 2. XU LY CHUP 1 ANH TINH (SNAPSHOT /capture)
static esp_err_t capture_handler(httpd_req_t *req) {
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }
    httpd_resp_set_type(req, "image/jpeg");
    httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store, private");
    esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
    esp_camera_fb_return(fb);
    return res;
}

// Ten cam bien theo ma PID (so thuan de bien dich duoc voi moi phien ban core esp32)
static const char* sensor_name(unsigned pid) {
    switch (pid) {
        case 0x26:   return "OV2640";
        case 0x3660: return "OV3660";
        case 0x5640: return "OV5640";
        default:     return "khac";
    }
}

// Kich thuoc khung hinh thuc te (pixel) cua do phan giai dang chay
static void frame_dims(sensor_t *s, unsigned *w, unsigned *h) {
    *w = 0;
    *h = 0;
    if (s->status.framesize < FRAMESIZE_INVALID) {
        *w = resolution[s->status.framesize].width;
        *h = resolution[s->status.framesize].height;
    }
}

// 3. XU LY THONG TIN TRANG THAI CAM BIEN (/status) GIONG CameraWebServer
static esp_err_t status_handler(httpd_req_t *req) {
    static char json_response[1024];
    sensor_t * s = esp_camera_sensor_get();
    if (s == NULL) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }
    String ip_str = is_sta_mode ? WiFi.localIP().toString() : WiFi.softAPIP().toString();
    char rssi_str[12];
    if (is_sta_mode) {
        snprintf(rssi_str, sizeof(rssi_str), "%d", (int)WiFi.RSSI());
    } else {
        snprintf(rssi_str, sizeof(rssi_str), "null");
    }
    unsigned width = 0, height = 0;
    frame_dims(s, &width, &height);

    int n = snprintf(json_response, sizeof(json_response),
             "{\"framesize\":%u,\"width\":%u,\"height\":%u,\"quality\":%u,\"psram\":%s,"
             "\"wifi_mode\":\"%s\",\"ip\":\"%s\",\"rssi\":%s,\"hostname\":\"%s\","
             "\"stream_fps\":%u,\"free_heap\":%u,\"uptime_s\":%u,"
             "\"sensor\":\"%s\",\"sensor_pid\":\"0x%x\","
             "\"awb\":%u,\"awb_gain\":%u,\"wb_mode\":%u,"
             "\"aec\":%u,\"aec2\":%u,\"ae_level\":%d,\"aec_value\":%u,"
             "\"agc\":%u,\"agc_gain\":%u,\"gainceiling\":%u,"
             "\"brightness\":%d,\"contrast\":%d,\"saturation\":%d,\"sharpness\":%d,"
             "\"special_effect\":%u,\"lenc\":%u,\"raw_gma\":%u,\"bpc\":%u,\"wpc\":%u,\"dcw\":%u,"
             "\"vflip\":%u,\"hmirror\":%u}",
             (unsigned)s->status.framesize, width, height, (unsigned)s->status.quality,
             psramFound() ? "true" : "false",
             is_sta_mode ? "sta" : "ap", ip_str.c_str(), rssi_str, CAMERA_HOSTNAME,
             (unsigned)stream_fps, (unsigned)ESP.getFreeHeap(), (unsigned)(millis() / 1000),
             sensor_name(s->id.PID), (unsigned)s->id.PID,
             (unsigned)s->status.awb, (unsigned)s->status.awb_gain, (unsigned)s->status.wb_mode,
             (unsigned)s->status.aec, (unsigned)s->status.aec2, (int)s->status.ae_level, (unsigned)s->status.aec_value,
             (unsigned)s->status.agc, (unsigned)s->status.agc_gain, (unsigned)s->status.gainceiling,
             (int)s->status.brightness, (int)s->status.contrast, (int)s->status.saturation, (int)s->status.sharpness,
             (unsigned)s->status.special_effect, (unsigned)s->status.lenc, (unsigned)s->status.raw_gma,
             (unsigned)s->status.bpc, (unsigned)s->status.wpc, (unsigned)s->status.dcw,
             (unsigned)s->status.vflip, (unsigned)s->status.hmirror);
    if (n < 0 || n >= (int)sizeof(json_response)) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    return httpd_resp_send(req, json_response, n);
}

// Tra loi 400 kem ly do cho /control
static esp_err_t control_error(httpd_req_t *req, const char *message) {
    char body[96];
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}", message);
    httpd_resp_set_status(req, "400 Bad Request");
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
}

// Doi ten do phan giai thanh ma enum. Dung TEN (QVGA/CIF/HVGA/VGA) thi khong phu thuoc
// phien ban core esp32, vi so thu tu enum khac nhau giua cac phien ban.
static int framesize_from_text(const char *text) {
    if (strcasecmp(text, "QVGA") == 0) return FRAMESIZE_QVGA;
    if (strcasecmp(text, "CIF") == 0)  return FRAMESIZE_CIF;
    if (strcasecmp(text, "HVGA") == 0) return FRAMESIZE_HVGA;
    if (strcasecmp(text, "VGA") == 0)  return FRAMESIZE_VGA;
    return -1;
}

// Mot bien so nguyen cua /control: kiem tra khoang hop le roi goi ham set_* cua cam bien
#define CONTROL_INT_VAR(NAME, LOW, HIGH, CALL)                                   \
    else if (strcmp(variable, NAME) == 0) {                                      \
        if (!has_int || val < (LOW) || val > (HIGH)) {                           \
            return control_error(req, "Invalid value");                          \
        }                                                                        \
        rc = (CALL);                                                             \
    }

// 4. XU LY DIEU KHIEN THONG SO CAM BIEN (/control?var=...&val=...)
static esp_err_t control_handler(httpd_req_t *req) {
    char *buf = NULL;
    size_t buf_len = httpd_req_get_url_query_len(req) + 1;
    if (buf_len <= 1) {
        return control_error(req, "Missing query parameters");
    }
    buf = (char *)malloc(buf_len);
    if (!buf) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }
    if (httpd_req_get_url_query_str(req, buf, buf_len) != ESP_OK) {
        free(buf);
        return control_error(req, "Invalid query");
    }

    char variable[32] = {0};
    char value[32] = {0};
    if (httpd_query_key_value(buf, "var", variable, sizeof(variable)) != ESP_OK ||
        httpd_query_key_value(buf, "val", value, sizeof(value)) != ESP_OK) {
        free(buf);
        return control_error(req, "Missing var or val");
    }
    free(buf);

    char *value_end = NULL;
    long parsed = strtol(value, &value_end, 10);
    bool has_int = (value_end != value && *value_end == '\0');
    int val = has_int ? (int)parsed : 0;

    sensor_t *s = esp_camera_sensor_get();
    if (s == NULL) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }

    int rc = 0;
    if (strcmp(variable, "framesize") == 0) {
        int fs = framesize_from_text(value);
        if (fs < 0 && has_int) {
            fs = val;
        }
        bool valid = (fs == FRAMESIZE_QVGA);
        if (psramFound() && (fs == FRAMESIZE_CIF || fs == FRAMESIZE_HVGA || fs == FRAMESIZE_VGA)) {
            valid = true;
        }
        if (!valid) {
            return control_error(req, "Invalid framesize");
        }
        rc = s->set_framesize(s, (framesize_t)fs);
    } else if (strcmp(variable, "quality") == 0) {
        if (!has_int || val < 10 || val > 30) {
            return control_error(req, "Invalid quality");
        }
        rc = s->set_quality(s, val);
    }
    CONTROL_INT_VAR("awb", 0, 1, s->set_whitebal(s, val))
    CONTROL_INT_VAR("awb_gain", 0, 1, s->set_awb_gain(s, val))
    CONTROL_INT_VAR("wb_mode", 0, 4, s->set_wb_mode(s, val))
    CONTROL_INT_VAR("aec", 0, 1, s->set_exposure_ctrl(s, val))
    CONTROL_INT_VAR("aec2", 0, 1, s->set_aec2(s, val))
    CONTROL_INT_VAR("ae_level", -2, 2, s->set_ae_level(s, val))
    CONTROL_INT_VAR("aec_value", 0, 1200, s->set_aec_value(s, val))
    CONTROL_INT_VAR("agc", 0, 1, s->set_gain_ctrl(s, val))
    CONTROL_INT_VAR("agc_gain", 0, 30, s->set_agc_gain(s, val))
    CONTROL_INT_VAR("gainceiling", 0, 6, s->set_gainceiling(s, (gainceiling_t)val))
    CONTROL_INT_VAR("brightness", -2, 2, s->set_brightness(s, val))
    CONTROL_INT_VAR("contrast", -2, 2, s->set_contrast(s, val))
    CONTROL_INT_VAR("saturation", -2, 2, s->set_saturation(s, val))
    CONTROL_INT_VAR("sharpness", -2, 2, s->set_sharpness(s, val))
    CONTROL_INT_VAR("special_effect", 0, 6, s->set_special_effect(s, val))
    CONTROL_INT_VAR("lenc", 0, 1, s->set_lenc(s, val))
    CONTROL_INT_VAR("raw_gma", 0, 1, s->set_raw_gma(s, val))
    CONTROL_INT_VAR("bpc", 0, 1, s->set_bpc(s, val))
    CONTROL_INT_VAR("wpc", 0, 1, s->set_wpc(s, val))
    CONTROL_INT_VAR("dcw", 0, 1, s->set_dcw(s, val))
    CONTROL_INT_VAR("vflip", 0, 1, s->set_vflip(s, val))
    CONTROL_INT_VAR("hmirror", 0, 1, s->set_hmirror(s, val))
    else {
        return control_error(req, "Unknown variable");
    }

    if (rc != 0) {
        // Cam bien khong nhan gia tri nay (vi du OV2640 khong ho tro sharpness)
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }

    unsigned width = 0, height = 0;
    frame_dims(s, &width, &height);
    char response[160];
    snprintf(response, sizeof(response),
             "{\"ok\":true,\"framesize\":%u,\"width\":%u,\"height\":%u,\"quality\":%u}",
             (unsigned)s->status.framesize, width, height, (unsigned)s->status.quality);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    return httpd_resp_send(req, response, strlen(response));
}

// 5. XU LY NHAY DEN FLASH KHI DIEM DANH THANH CONG (/flash)
void flash_task(void *pvParameters) {
    digitalWrite(FLASH_GPIO_NUM, HIGH); // Bat den Flash
    vTaskDelay(pdMS_TO_TICKS(150));     // Sang trong 150ms
    digitalWrite(FLASH_GPIO_NUM, LOW);  // Tat den Flash
    vTaskDelete(NULL);                  // Tu huy task
}

static esp_err_t flash_handler(httpd_req_t *req) {
    // Tao task FreeRTOS chay ngam chop den, khong chan luong video stream
    xTaskCreate(flash_task, "flash_task", 1024, NULL, 1, NULL);
    httpd_resp_set_type(req, "text/plain");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    return httpd_resp_send(req, "OK", 2);
}

void startCameraServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 8;

    // Server 1 (Port 80): phuc vu /capture, /status, /control, /flash (giong CameraWebServer)
    config.server_port = 80;
    config.ctrl_port = 32768;

    httpd_uri_t capture_uri = {
        .uri       = "/capture",
        .method    = HTTP_GET,
        .handler   = capture_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t status_uri = {
        .uri       = "/status",
        .method    = HTTP_GET,
        .handler   = status_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t control_uri = {
        .uri       = "/control",
        .method    = HTTP_GET,
        .handler   = control_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t flash_uri = {
        .uri       = "/flash",
        .method    = HTTP_GET,
        .handler   = flash_handler,
        .user_ctx  = NULL
    };

    if (httpd_start(&camera_httpd, &config) == ESP_OK) {
        httpd_register_uri_handler(camera_httpd, &capture_uri);
        httpd_register_uri_handler(camera_httpd, &status_uri);
        httpd_register_uri_handler(camera_httpd, &control_uri);
        httpd_register_uri_handler(camera_httpd, &flash_uri);
    }

    // Server 2 (Port 81): tach rieng chuyen phuc vu /stream video MJPEG
    config.server_port = 81;
    config.ctrl_port = 32769;

    httpd_uri_t stream_uri = {
        .uri       = "/stream",
        .method    = HTTP_GET,
        .handler   = stream_handler,
        .user_ctx  = NULL
    };

    if (httpd_start(&stream_httpd, &config) == ESP_OK) {
        httpd_register_uri_handler(stream_httpd, &stream_uri);
    }
}

void setup() {
#ifdef DISABLE_BROWNOUT
    // Canh bao: Chi tat brownout detector khi nguon cap 5V yeu/sut ap luc phat Wi-Fi.
    // Khuyen nghi phan cung: dung nguon 5V/2A on dinh va gan tu loc 100uF-470uF.
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
#endif

    Serial.begin(9600);
    delay(500);
    Serial.println("\n--- DANG KHOI DONG ESP32-CAM ---");

    pinMode(LED_BUILTIN_RED, OUTPUT);
    digitalWrite(LED_BUILTIN_RED, HIGH); // Tat den ban dau

    pinMode(FLASH_GPIO_NUM, OUTPUT);
    digitalWrite(FLASH_GPIO_NUM, LOW);  // Tat den Flash ban dau

    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.grab_mode = CAMERA_GRAB_LATEST;

    // Kiem tra ho tro PSRAM de toi uu hoa frame buffer
    // Nguon: CameraWebServer.ino trong arduino-esp32 & esp_camera.h
    if (psramFound()) {
        // Init o VGA de cap san bo dem lon trong PSRAM, tranh tran bo dem FB-OVF khi doi do phan giai qua /control
        config.frame_size = FRAMESIZE_VGA;
        config.jpeg_quality = 12;           // 10-12 la dai tieu chuan cua CameraWebServer
        config.fb_count = 2;                // Double buffer trong PSRAM tranh xe hinh
        config.fb_location = CAMERA_FB_IN_PSRAM;
    } else {
        // Fallback khi board khong co hoac khong nhan PSRAM: dung DRAM noi bo
        config.frame_size = FRAMESIZE_QVGA; // 320x240 de tranh tran DRAM
        config.jpeg_quality = 12;
        config.fb_count = 1;                // 1 buffer trong DRAM
        config.fb_location = CAMERA_FB_IN_DRAM;
    }

    // Khoi tao camera
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Loi khoi tao camera: 0x%x\n", err);
        return;
    }

    // ========================================================
    // CAU HINH CAM BIEN: DO PHAN GIAI, CAN BANG TRANG, PHOI SANG, CHONG NHIEU
    // ========================================================
    sensor_t * s = esp_camera_sensor_get();
    if (s != NULL) {
        Serial.printf("Cam bien: %s (PID 0x%x)\n", sensor_name(s->id.PID), (unsigned)s->id.PID);

        // Dat do phan giai chay TRUOC, roi moi dat mau va phoi sang, de cac thong so mau
        // khong bi ghi de khi cam bien doi che do. Bo dem da cap san co VGA nen /control doi len VGA duoc.
        if (psramFound()) {
            s->set_framesize(s, FRAMESIZE_QVGA);
            s->set_quality(s, 16);
        }

        s->set_whitebal(s, 1);       // 1 = Bat Auto White Balance (Can bang trang tu dong)
        s->set_awb_gain(s, 1);       // 1 = Bat AWB Gain (Tang do nhay can bang mau)
        s->set_wb_mode(s, 0);        // 0 = Auto (Tu dong dieu chinh theo anh sang phong)
        s->set_exposure_ctrl(s, 1);  // 1 = Bat phoi sang tu dong (AEC)
        s->set_aec2(s, 1);           // 1 = Bat tinh nang do sang nang cao
        s->set_ae_level(s, 0);       // 0 = Muc phoi sang chuan (-2 den 2)
        s->set_brightness(s, 0);     // 0 = Do sang tieu chuan (-2 den 2)
        s->set_contrast(s, 0);       // 0 = Do tuong phan tieu chuan (-2 den 2)
        s->set_saturation(s, 0);     // 0 = Do bao hoa mau chuan (-2 den 2)
        s->set_special_effect(s, 0); // 0 = Khong hieu ung mau (No Effect)
        s->set_gainceiling(s, (gainceiling_t)2);
        s->set_raw_gma(s, 1);        // 1 = Gamma correction giup anh trong va ro net
        s->set_lenc(s, 1);           // 1 = Lens correction chong toi 4 goc ong kinh
        s->set_bpc(s, 1);            // 1 = Khu diem chet den (Black pixel correction)
        s->set_wpc(s, 1);            // 1 = Khu diem chet trang (White pixel correction)
        s->set_dcw(s, 1);            // 1 = Chuan hoa ma tran mau sac

        // OV3660 can cac thong so rieng (theo CameraWebServer.ino cua Espressif)
        if (s->id.PID == 0x3660) {
            s->set_vflip(s, 1);
            s->set_brightness(s, 1);
            s->set_saturation(s, -2);
        }

        unsigned width = 0, height = 0;
        frame_dims(s, &width, &height);
        Serial.printf("Do phan giai: %ux%u (ma %u)\n", width, height, (unsigned)s->status.framesize);

        // Bo cac khung hinh dau trong 0,8 giay de can bang trang va phoi sang kip on dinh
        unsigned long warmup_start = millis();
        while (millis() - warmup_start < 800) {
            camera_fb_t *warmup_fb = esp_camera_fb_get();
            if (warmup_fb) {
                esp_camera_fb_return(warmup_fb);
            } else {
                delay(10);
            }
        }
    }

    // ========================================================
    // KHOI TAO WI-FI: THU KET NOI STA TRUOC, THAT BAI VE AP
    // ========================================================
    bool should_try_sta = (strlen(WIFI_SSID) > 0 && strcmp(WIFI_SSID, "YOUR_PHONE_HOTSPOT") != 0);

    if (should_try_sta) {
        Serial.printf("Dang ket noi Wi-Fi STA toi: %s ...\n", WIFI_SSID);
        WiFi.mode(WIFI_STA);
        WiFi.setHostname(CAMERA_HOSTNAME);
        WiFi.setSleep(false);
        WiFi.setAutoReconnect(true);
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

        unsigned long start_attempt = millis();
        bool led_state = false;
        while (WiFi.status() != WL_CONNECTED && (millis() - start_attempt < WIFI_CONNECT_TIMEOUT_MS)) {
            led_state = !led_state;
            digitalWrite(LED_BUILTIN_RED, led_state ? LOW : HIGH);
            delay(200);
            Serial.print(".");
        }
        digitalWrite(LED_BUILTIN_RED, HIGH);
        Serial.println();

        if (WiFi.status() == WL_CONNECTED) {
            is_sta_mode = true;
            esp_wifi_set_ps(WIFI_PS_NONE);
            if (WIFI_TX_POWER_MAX) {
                WiFi.setTxPower(WIFI_POWER_19_5dBm);
            }
            MDNS.begin(CAMERA_HOSTNAME);
            MDNS.addService("http", "tcp", 80);
        } else {
            Serial.println("Ket noi Wi-Fi STA that bai hoac qua thoi gian! Chuyen ve che do AP...");
            WiFi.disconnect(true);
            WiFi.mode(WIFI_AP);
            WiFi.setSleep(false);
            if (!WiFi.softAP(AP_SSID, AP_PASSWORD)) {
                Serial.println("Loi tao diem phat song Wi-Fi AP!");
                return;
            }
            is_sta_mode = false;
        }
    } else {
        WiFi.mode(WIFI_AP);
        WiFi.setSleep(false);
        if (!WiFi.softAP(AP_SSID, AP_PASSWORD)) {
            Serial.println("Loi tao diem phat song Wi-Fi AP!");
            return;
        }
        is_sta_mode = false;
    }

    startCameraServer();

    IPAddress ip = is_sta_mode ? WiFi.localIP() : WiFi.softAPIP();

    Serial.println("\n========================================");
    if (is_sta_mode) {
        Serial.println(">>> ESP32 KET NOI WI-FI THANH CONG! <<<");
        Serial.println("CHE DO: STA (hotspot)");
        Serial.print("SSID: ");
        Serial.println(WIFI_SSID);
        Serial.print("RSSI: ");
        Serial.print(WiFi.RSSI());
        Serial.println(" dBm");
    } else {
        Serial.println(">>> ESP32 PHAT WI-FI THANH CONG! <<<");
        Serial.println("CHE DO: AP (tu phat)");
        Serial.print("TEN WI-FI (SSID): ");
        Serial.println(AP_SSID);
        Serial.print("MAT KHAU: ");
        Serial.println(AP_PASSWORD);
    }
    Serial.print("DIA CHI IP: ");
    Serial.println(ip);
    Serial.print("PORT 80 (CAPTURE/STATUS): http://");
    Serial.print(ip);
    Serial.println("/capture");
    Serial.print("PORT 81 (STREAM MJPEG):    http://");
    Serial.print(ip);
    Serial.println(":81/stream");
    if (is_sta_mode) {
        Serial.print("MDNS URL (STREAM MJPEG):   http://");
        Serial.print(CAMERA_HOSTNAME);
        Serial.println(".local:81/stream");
    }
    Serial.println("========================================\n");

    // Nhap nhay den LED bao san sang
    for(int i = 0; i < 3; i++) {
        digitalWrite(LED_BUILTIN_RED, LOW);
        delay(200);
        digitalWrite(LED_BUILTIN_RED, HIGH);
        delay(200);
    }
}

void loop() {
    static unsigned long last_fps_calc = 0;
    static uint32_t last_frame_count = 0;

    unsigned long now = millis();
    if (now - last_fps_calc >= 1000) {
        uint32_t current_count = stream_frame_count;
        stream_fps = current_count - last_frame_count;
        last_frame_count = current_count;
        last_fps_calc = now;
    }
    delay(50);
}
