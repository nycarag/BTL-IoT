#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include "soc/soc.h"             // Thu vien quan ly nguon
#include "soc/rtc_cntl_reg.h"    // Thu vien tat brownout (chong sap nguon)

// ========================================================
// 1. CAU HINH WI-FI DO ESP32-CAM TU PHAT RA (ACCESS POINT)
// IP CO DINH VINH VIEN: 192.168.4.1
// ========================================================
const char* ap_ssid = "ESP32_DIEM_DANH";
const char* ap_password = "12345678"; // Mat khau it nhat 8 ky tu

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
        }
        // Neu client dong ket noi hoac loi mang -> THOAT NGAY de giai phong bo dem
        if(res != ESP_OK) {
            break;
        }
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
    esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
    esp_camera_fb_return(fb);
    return res;
}

// 3. XU LY NHAY DEN FLASH KHI DIEM DANH THANH CONG (/flash)
void flash_task(void *pvParameters) {
    digitalWrite(FLASH_GPIO_NUM, HIGH); // Bat den Flash
    vTaskDelay(pdMS_TO_TICKS(150));     // Sang trong 150ms
    digitalWrite(FLASH_GPIO_NUM, LOW);  // Tat den Flash
    vTaskDelete(NULL);                  // Tu huy task
}

static esp_err_t flash_handler(httpd_req_t *req) {
    // Tao task FreeRTOS chay ngam chớp đèn, không chặn luồng video stream
    xTaskCreate(flash_task, "flash_task", 1024, NULL, 1, NULL);
    httpd_resp_set_type(req, "text/plain");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    return httpd_resp_send(req, "OK", 2);
}

void startCameraServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 81;
    config.ctrl_port = 32768;

    httpd_uri_t stream_uri = {
        .uri       = "/stream",
        .method    = HTTP_GET,
        .handler   = stream_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t capture_uri = {
        .uri       = "/capture",
        .method    = HTTP_GET,
        .handler   = capture_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t flash_uri = {
        .uri       = "/flash",
        .method    = HTTP_GET,
        .handler   = flash_handler,
        .user_ctx  = NULL
    };

    if (httpd_start(&stream_httpd, &config) == ESP_OK) {
        httpd_register_uri_handler(stream_httpd, &stream_uri);
        httpd_register_uri_handler(stream_httpd, &capture_uri);
        httpd_register_uri_handler(stream_httpd, &flash_uri);
    }
}

void setup() {
    // TAT BROWNOUT DETECTOR (CHONG SAP NGUON)
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

    Serial.begin(9600);
    delay(500);
    Serial.println("\n--- DANG KHOI DONG ESP32-CAM (CHE DO TU PHAT WI-FI) ---");

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
    config.frame_size = FRAMESIZE_CIF; // 400x296: Sieu muot 25-30 FPS, do tre cuc thap, giam nong mach
    config.jpeg_quality = 12;
    config.fb_count = 2;

    // Khoi tao camera
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Loi khoi tao camera: 0x%x\n", err);
        return;
    }

    // ========================================================
    // CAU HINH CAM BIEN OV2640: KHU AM XANH, CAN BANG TRANG, CHONG NHIEU
    // ========================================================
    sensor_t * s = esp_camera_sensor_get();
    if (s != NULL) {
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
    }

    // KHOI TAO DIEM PHAT SONG ACCESS POINT
    WiFi.mode(WIFI_AP);
    bool ap_ok = WiFi.softAP(ap_ssid, ap_password);
    if (!ap_ok) {
        Serial.println("Loi tao diem phat song Wi-Fi!");
        return;
    }

    startCameraServer();

    Serial.println("\n========================================");
    Serial.println(">>> ESP32 PHAT WI-FI THANH CONG! <<<");
    Serial.print("TEN WI-FI: ");
    Serial.println(ap_ssid);
    Serial.print("MAT KHAU: ");
    Serial.println(ap_password);
    Serial.print("DIA CHI IP CO DINH: ");
    Serial.println(WiFi.softAPIP());
    Serial.print("LINK STREAM VIDEO: http://");
    Serial.print(WiFi.softAPIP());
    Serial.println(":81/stream");
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
    delay(10000);
}
