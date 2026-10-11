---
title: 24/7 YouTube Live Streaming System
emoji: 📡
colorFrom: red
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 24/7 YouTube Live Streaming System

> `asd.video` tabanlı video kaynağını sürekli döngüye alarak FFmpeg üzerinden YouTube Live'a 7/24 yayın yapan otomatik yayın sistemi.

## 📌 Proje Hakkında

Bu proje, bir video kaynağını (`asd.video`) otomatik olarak alıp **FFmpeg** ile sürekli döngüye sokarak **YouTube Live** üzerinden kesintisiz yayınlamayı amaçlar.

Sistem, yayın bağlantısı koptuğunda otomatik olarak yeniden bağlanabilir ve uygulama yeniden başlatıldığında yayın sürecini otomatik olarak tekrar başlatabilir.

Temel amaç:

```text
asd.video
    ↓
Video Source
    ↓
FFmpeg
    ↓
Loop
    ↓
YouTube RTMP
    ↓
YouTube Live
    ↓
24/7 Yayın
```

---

# 🎯 Özellikler

## 🎬 Video Sistemi

* `asd.video` video kaynağını destekleme
* Yerel video desteği
* HTTP/HTTPS video kaynağı desteği
* Birden fazla video desteği
* Playlist sistemi
* Otomatik video geçişi
* Sonsuz video loop
* Video bittiğinde otomatik yeniden başlatma

## 📡 Multi-Stream (YouTube, Kick.com, Nimo TV & TikTok Live)
* **YouTube Live** (RTMP & RTMPS)
* **Kick.com** (Amazon IVS RTMPS Ingestion)
* **Nimo TV** (RTMP; signed stream key)
* **TikTok Live** (RTMP/RTMPS Ingestion - Dikey 9:16 ve yatay yayın desteği)
* TikTok oturum çerezi bir kez güvenli biçimde kaydedildikten sonra yayın odası ve RTMP anahtarı otomatik oluşturulur.
* Oda oluşturmadan önce sessionid TikTok hesap API'si üzerinden doğrulanır; reddedilen/doğrulanamayan oturumlarda oda oluşturma isteği gönderilmez.
* TikTok geçici oda kilidi (10037/20800) döndürürse diğer platformlar yayın yapmayı sürdürür; oda oluşturma 30 saniyeden başlayıp en çok 5 dakikada bir otomatik denenir ve TikTok hazır olunca akışa eklenir.
* İsteğe bağlı TikTok LIVE Etkinlik URL'si veya ID'si oda oluşturma isteğine aktarılır; TikTok'un etkinlik erişimine göre yayın odası etkinliğe bağlanabilir.
* Tek seferde birden fazla platforma eşzamanlı yayınlama (FFmpeg `tee` muxer)
* Platform bazlı bağımsız Açma/Kapama (Toggle) kontrolü
* Platform stream key yönetimi ve güvenli maskeleme
* Bir platform kopsa dahi diğer platformların kesilmesini önleyen hata izolasyonu (`onfail=ignore`)
* Otomatik yayın başlatma
* Yayın bağlantısı koparsa otomatik yeniden bağlanma (Watchdog)
* FFmpeg `tee` pseudo-muxer ile sıfır ek CPU yüküyle çoklu akış
* Yayın durumunun anlık takip edilmesi

## 🔄 24/7 Çalışma

Sistem mümkün olduğunca kesintisiz çalışacak şekilde tasarlanacaktır.

Örneğin:

```text
FFmpeg çalışıyor
      ↓
Video oynuyor
      ↓
YouTube bağlantısı var
      ↓
Yayın devam ediyor
```

Bağlantı koparsa:

```text
YouTube bağlantısı koptu
      ↓
Sistem hatayı algılar
      ↓
FFmpeg durdurulur
      ↓
Kısa süre beklenir
      ↓
FFmpeg yeniden başlatılır
      ↓
YouTube bağlantısı tekrar kurulur
```

---

# ☁️ Hugging Face

Projenin Docker sürümü **Hugging Face Spaces** üzerinde çalıştırılabilir.

Örnek:

```text
Hugging Face Space
        │
        ├── Web Panel
        ├── FFmpeg
        ├── Video Manager
        ├── Stream Manager
        └── Health Check
```

Örnek Space:

```text
https://YOUR-SPACE.hf.space
```

## ⚠️ Hugging Face Uyku / Kaynak Durumu

Hugging Face Space'in sürekli çalışması garanti edilmemelidir.

Bu nedenle sistem:

* Space yeniden başlatıldığında otomatik başlayabilmeli
* FFmpeg işlemini yeniden oluşturabilmeli
* YouTube bağlantısını tekrar kurabilmeli
* Video loop'u yeniden başlatabilmeli
* Sağlık kontrolü gerçekleştirebilmeli

şeklinde tasarlanmalıdır.

> Uptime servisleri Space'e düzenli HTTP istekleri göndermek için kullanılabilir; ancak bu yöntem tek başına 7/24 çalışma garantisi değildir.

### Eshanio M3U yönetimi

The `eshanio/hf_video_platform` Node API and M3U manager run alongside this
FastAPI application in the same Docker Space. Open
`https://eshansayhan-hotlink.hf.space/m3u-admin` after deployment. Configure
`M3U_ADMIN_API_KEY` as a Hugging Face Secret and set
`PUBLIC_BASE_URL=https://eshansayhan-hotlink.hf.space` as a Space variable.
Keep `/data` on persistent storage if M3U shares must survive Space restarts.
The FastAPI app proxies the M3U panel and video requests through the public
Space hostname; the Node and catalog services remain internal to the container.

### Safetensors video sources

The Eshanio player discovers `.safetensors` files from the configured Hugging
Face dataset and requests each video with both its tensor name and source file.
This keeps repeated tensor names such as `video_0000` isolated to their own
file. The API validates `source_file` against the dataset tree and rejects
ambiguous legacy stream requests unless `SAFETENSORS_DEFAULT_FILE` is configured.
The backend's `HF_DATASET_REPO` and `HF_DATASET_REVISION` must match the dataset
and revision configured by the player.

---

# 🤖 Otomatik Recovery

Sistemin en önemli parçalarından biri otomatik kurtarma mekanizmasıdır.

Örnek:

```text
                 ┌──────────────┐
                 │ FFmpeg       │
                 │ çalışıyor    │
                 └──────┬───────┘
                        │
                        ▼
                 YouTube bağlantısı
                        │
                ┌───────┴────────┐
                │                │
              OK             ERROR
                │                │
                ▼                ▼
             Devam          Retry sistemi
                                 │
                                 ▼
                            FFmpeg restart
                                 │
                                 ▼
                         YouTube reconnect
```

## Retry Sistemi

Örneğin:

```text
Deneme 1 → 5 saniye
Deneme 2 → 10 saniye
Deneme 3 → 20 saniye
Deneme 4 → 30 saniye
Deneme 5 → 60 saniye
```

Başarılı bağlantı kurulduğunda sayaç sıfırlanır.

---

# 🎥 Video Kaynağı

Sistem aşağıdaki gibi bir kaynak kullanabilir:

```text
asd.video
```

Örneğin:

```text
https://example.com/asd.video
```

veya:

```text
https://example.com/videos/asd.video
```

Uygulama bu kaynağı FFmpeg'e aktarır.

Örnek mantık:

```text
Video URL
   ↓
Source Manager
   ↓
FFmpeg
   ↓
Loop
   ↓
RTMP
```

---

# 🔁 Loop Sistemi

Video tamamlandığında otomatik olarak tekrar başlatılır.

```text
┌─────────────┐
│   VIDEO     │
│             │
│ 00:00 → 1:00│
└──────┬──────┘
       │
       ▼
   VIDEO BİTTİ
       │
       ▼
   BAŞA DÖN
       │
       └──────────────┐
                      │
                      ▼
                 00:00 → 1:00
```

Playlist kullanılırsa:

```text
video1.video
      ↓
video2.video
      ↓
video3.video
      ↓
video4.video
      ↓
video1.video
      ↓
       LOOP
```

---

# 📺 YouTube RTMP

YouTube yayın bilgileri uygulama tarafından kullanılabilir:

```text
RTMP URL:
rtmps://....

Stream Key:
***************
```

### Güvenlik

**Stream Key hiçbir zaman GitHub'a commit edilmemelidir.**

Önerilen yöntem:

```text
Environment Variables
```

Örneğin:

```text
YOUTUBE_RTMP_URL
YOUTUBE_STREAM_KEY
VIDEO_SOURCE
```

Hugging Face Secrets / Environment Variables kullanılmalıdır.

---

# 🖥️ Web Panel

Projeye basit bir web yönetim paneli eklenebilir.

Örnek:

```text
┌──────────────────────────────────────┐
│       24/7 STREAM CONTROL            │
├──────────────────────────────────────┤
│                                      │
│ Status: 🟢 LIVE                      │
│                                      │
│ Source: asd.video                    │
│                                      │
│ YouTube: Connected                   │
│                                      │
│ Uptime: 18h 42m                      │
│                                      │
│ [ START STREAM ]                     │
│ [ STOP STREAM ]                      │
│ [ RESTART STREAM ]                   │
│                                      │
└──────────────────────────────────────┘
```

---

# 📊 Sistem Durumu

Panel aşağıdaki bilgileri gösterebilir:

* Yayın durumu
* FFmpeg durumu
* YouTube bağlantısı
* Video adı
* Video süresi
* Geçen süre
* Uptime
* Yeniden bağlanma sayısı
* Son hata
* CPU kullanımı
* RAM kullanımı
* FFmpeg PID

Örnek:

```text
STREAM      : LIVE
SOURCE      : asd.video
YOUTUBE     : CONNECTED
FFMPEG      : RUNNING
UPTIME      : 18:42:12
RECONNECTS  : 2
```

---

# 🏗️ Proje Mimarisi

Önerilen klasör yapısı:

```text
project/
│
├── app/
│   ├── main.py
│   ├── config.py
│   ├── routes.py
│   │
│   ├── streamer/
│   │   ├── ffmpeg.py
│   │   ├── youtube.py
│   │   ├── loop.py
│   │   └── recovery.py
│   │
│   ├── video/
│   │   ├── source.py
│   │   ├── playlist.py
│   │   └── validator.py
│   │
│   └── monitoring/
│       ├── health.py
│       └── logger.py
│
├── web/
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── videos/
│
├── Dockerfile
├── requirements.txt
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

# 🐳 Docker

Hugging Face üzerinde çalıştırmak için Docker kullanılabilir.

Örnek:

```text
Docker
 ├── Python
 ├── FFmpeg
 ├── Web Server
 └── Stream Manager
```

Docker container başladığında:

```text
Container Start
      ↓
Application Start
      ↓
Configuration Load
      ↓
Video Source Check
      ↓
FFmpeg Start
      ↓
YouTube Connection
      ↓
24/7 Stream
```

---

# 🔐 Environment Variables

`.env.example`:

```env
PORT=7860
YOUTUBE_RTMP_URL=rtmp://a.rtmp.youtube.com/live2
YOUTUBE_STREAM_KEY=YOUR_STREAM_KEY

NIMO_ENABLED=true
NIMO_RTMP_URL=rtmp://alpush.rtmp.nimo.tv/live/
NIMO_STREAM_KEY=YOUR_NIMO_SIGNED_STREAM_KEY

VIDEO_SOURCE=asd.video

STREAM_WIDTH=1920
STREAM_HEIGHT=1080
STREAM_FPS=30
STREAM_BITRATE=4500k
STREAM_AUDIO_BITRATE=160k

VIDEO_LOOP=true
AUTO_START=true

RECONNECT_ENABLED=true
RECONNECT_MAX_RETRIES=0
RECONNECT_INITIAL_DELAY=5
RECONNECT_MAX_DELAY=60
```

Nimo'nun RTMP adresinde sunucu adresi ve signed stream key ayrı alanlara yazılmalıdır.
`NIMO_STREAM_KEY` değerine stream key'in query string dahil tamamını girin; bu imzalı anahtarı paylaşmayın.
Gerçek `.env` dosyası GitHub'a yüklenmemelidir.
Yerel gizli değerleri `.env.local` dosyasında saklayın; bu dosya Git tarafından yok sayılır.
Docker Compose'u her iki ayar dosyasıyla çalıştırmak için `docker compose --env-file .env --env-file .env.local up` kullanın.

---

# 🛡️ Güvenlik

Aşağıdaki bilgiler gizli tutulmalıdır:

* YouTube Stream Key
* Nimo TV Signed Stream Key
* API Keys
* Admin Password
* Private URLs
* Access Tokens

`.gitignore`:

```gitignore
.env
*.key
*.secret
secrets/
videos/*
!videos/.gitkeep
```

---

# ❤️ Health Check

Uygulama aşağıdaki endpoint'i sağlayabilir:

```text
GET /health
```

Örnek cevap:

```json
{
  "status": "ok",
  "stream": "running",
  "ffmpeg": "running",
  "youtube": "connected"
}
```

Uptime monitoring servisi bu endpoint'i kontrol edebilir.

---

# 🔄 Watchdog

Watchdog sistemi FFmpeg'i kontrol eder.

```text
Watchdog
   │
   ├── FFmpeg çalışıyor → OK
   │
   └── FFmpeg durmuş
           ↓
       Restart FFmpeg
           ↓
       YouTube reconnect
```

Bu sayede uygulama beklenmeyen FFmpeg kapanmalarında kendini toparlayabilir.

---

# 🌐 Uptime Monitoring

Bir uptime monitoring servisi:

```text
https://YOUR-SPACE.hf.space/health
```

adresini belirli aralıklarla kontrol edebilir.

Amaç:

* HTTP endpoint'in çalışıp çalışmadığını görmek
* Uygulamanın erişilebilirliğini izlemek
* Hata durumunda bildirim almak

> Uptime monitoring, uygulamanın gerçekten sürekli çalışmasını garanti eden bir mekanizma değildir.

---

# 🚀 Çalışma Akışı

Tam sistem:

```text
                  USER
                   │
                   ▼
            Web Control Panel
                   │
                   ▼
          ┌──────────────────┐
          │ Stream Manager   │
          └────────┬─────────┘
                   │
                   ▼
              asd.video
                   │
                   ▼
                FFmpeg
                   │
                   ▼
                 LOOP
                   │
                   ▼
             YouTube RTMP
                   │
                   ▼
             YouTube Live
                   │
                   ▼
             🔴 24/7 LIVE
```

---

# 🧠 Recovery Akışı

```text
FFmpeg
  │
  ├── Running ───────────────► Continue
  │
  └── Stopped
        │
        ▼
   Detect Error
        │
        ▼
   Wait / Retry
        │
        ▼
   Start FFmpeg
        │
        ▼
   Connect YouTube
        │
        ├── Success ───────► Continue
        │
        └── Failed
                │
                ▼
             Retry
```

---

# 🛠️ Teknolojiler

Önerilen teknoloji stack'i:

* Python
* FastAPI
* FFmpeg
* Docker
* HTML
* CSS
* JavaScript
* Hugging Face Spaces
* YouTube Live / RTMP

Opsiyonel:

* Redis
* SQLite
* PostgreSQL
* WebSocket
* Prometheus
* Uptime monitoring

---

# 📋 Geliştirme Aşamaları

## Aşama 1 — Video

* [x] `asd.video` okuma
* [x] Video doğrulama
* [x] FFmpeg entegrasyonu
* [x] Loop sistemi

## Aşama 2 — YouTube

* [x] RTMP bağlantısı
* [x] Stream Key yönetimi
* [x] Yayın başlatma
* [x] Yayın durdurma

## Aşama 3 — Recovery

* [x] FFmpeg watchdog
* [x] YouTube reconnect
* [x] Automatic restart
* [x] Error handling

## Aşama 4 — Web Panel

* [x] Dashboard
* [x] Start
* [x] Stop
* [x] Restart
* [x] Status
* [x] Logs

## Aşama 5 — Hugging Face

* [x] Dockerfile
* [x] Space deployment
* [x] Environment variables
* [x] Secrets
* [x] Health endpoint

## Aşama 6 — Monitoring

* [x] `/health`
* [x] Uptime monitoring
* [x] Error logs
* [x] Notification system

---

# ⚠️ Kullanım Notu

Bu sistem yalnızca yayınlama hakkına sahip olduğunuz veya yayınlamaya izin verilen içerikler için kullanılmalıdır.

YouTube'un canlı yayın, telif hakkı ve platform kullanım kurallarına uyulmalıdır.

---

# 📜 License

MIT License

---

# 👨‍💻 Developer

**Eshan Sayhan**

Project: **24/7 Video → YouTube Live Streaming System**

## Discord kodlu HFStream erişimi

HFStream'de `/kod` komutu Discord üzerinden kişiye özel, 14 haneli bir kod
üretir. Kod ilk kullanımda tarayıcı cihazına bağlanır; kodun süresi yönetici
panelinde belirlenen saat kadar sürer (varsayılan 24 saat). Yönetici Discord
OAuth ile giriş yaparak misafirlerin görebileceği videoları, kod süresini ve
aktif kodları yönetebilir. Kod girişi olmadan katalog ve medya erişimi sunucu
tarafında varsayılan video listesiyle sınırlandırılır.

### Hugging Face Space kurulumu

1. Space ayarlarında **Persistent storage** etkinleştirin ve `/data` yoluna
   bağlayın. Erişim veritabanı aksi belirtilmedikçe
   `/data/hfstream-access.sqlite3` konumunda tutulur; kalıcı depolama olmadan
   yeniden oluşturulan container kodları ve yönetici ayarlarını kaybeder.
2. Space **Settings → Variables and secrets** bölümüne aşağıdaki gizli
   değerleri ekleyin. Token ve secret değerlerini kaynak koda koymayın.
   - `DISCORD_BOT_TOKEN`: Discord bot token'ı.
   - `HFSTREAM_ADMIN_PASSWORD`: yönetici paneli parolası; en az 16 karakter,
     tercihen parola yöneticisinde üretilmiş rastgele bir değer.
   - `HFSTREAM_AUTH_SECRET`: en az 32 rastgele karakterlik sabit imzalama
     sırrı; değiştirilmesi mevcut kod ve oturumları geçersiz kılar.
   - `HFSTREAM_PUBLIC_URL`: `https://eshansayhan-hotlink.hf.space`
3. Botun slash komutları oluşturabilmesi için botu sunucuya
   `applications.commands` yetkisiyle davet edin. İsteğe bağlı
   `DISCORD_GUILD_ID` ile komutları yalnızca sunucuda eşitleyin;
   `DISCORD_CHANNEL_ID` ile `/kod` komutunu tek bir kanalla sınırlandırın.
   Tanımlanmazsa botun bulunduğu tüm kanallarda `/kod` çalışır.
4. Uygulamayı yeniden başlatın. Discord kanalında `/kod` ile verilen bağlantı
   kodu giriş sayfasına taşır ve ilk cihazda etkinleştirir. Uygulamada
   **Kod / Yönetici → Yönetici girişi · Parola** akışını kullanarak paneli açın
   ve misafirlerin görebileceği varsayılan videoları seçin. Varsayılan seçim
   başlangıçta boştur. Yönetici parolası için IP başına dakikada en fazla 12
   deneme yapılabilir; oturum çerezi `HttpOnly` ve `Secure` olarak ayarlanır.

İsteğe bağlı değişkenler: `HFSTREAM_PUBLIC_URL`, `DISCORD_GUILD_ID`,
`DISCORD_CHANNEL_ID`, `HFSTREAM_ACCESS_DB`. `HFSTREAM_ACCESS_DB` kullanılırsa dosya yine kalıcı
depolamada olmalıdır.
