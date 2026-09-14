# AI Smart Glasses — Full Rebuild

Backend FastAPI + PostgreSQL, frontend PWA (IndexedDB, offline-first, online/offline AI sync), dan starting point firmware ESP32 — dibangun ulang sesuai spesifikasi di `ai-smart-glasses-build-prompt.docx`.

## ⚠️ Catatan Penting Sebelum Mulai

Proyek ini ditulis di lingkungan sandbox **tanpa akses internet** — artinya saya **tidak bisa** menjalankan `pip install`, menyalakan server sungguhan, menyambung ke PostgreSQL/Ollama asli, atau menjalankan `pytest` secara langsung di sini. Yang sudah saya lakukan untuk menjaga kualitas:

- Setiap file Python dicek dengan `python3 -m py_compile` (lolos semua — tidak ada *syntax error*).
- Kode ditulis & ditinjau manual mengikuti dokumentasi resmi FastAPI/asyncpg/Ollama yang saya kuasai.

Yang **belum** bisa saya pastikan karena keterbatasan itu: bug runtime yang hanya muncul saat benar-benar dijalankan (typo nama field, dsb.), kompatibilitas versi package persis, dan perilaku sebenarnya terhadap PostgreSQL/Ollama asli. **Langkah pertama yang wajib kamu lakukan** setelah ekstrak: jalankan `pytest` (lihat di bawah) untuk memverifikasi semuanya benar-benar berfungsi, sebelum deploy ke produksi.

## Struktur Proyek

```
ai-smart-glasses/
├── server/
│   ├── main.py              # FastAPI app & semua route
│   ├── config.py            # Baca konfigurasi dari environment variable
│   ├── database.py          # Koneksi PostgreSQL + fallback demo mode
│   ├── schema.sql           # Skema database (auto-dijalankan saat startup)
│   ├── models.py            # Dataclass untuk Device/Conversation/Message
│   ├── repositories.py      # Data access layer (Postgres + in-memory)
│   ├── device_auth.py       # Identitas anonim per-perangkat
│   ├── ai_router.py         # Memilih & memformat prompt online/offline
│   ├── online_ai.py         # Provider AI cloud (OpenAI-compatible generic)
│   ├── local_ai.py          # Provider AI lokal (Ollama)
│   ├── sync.py              # Logika sinkronisasi push/pull
│   ├── schemas.py           # Model request/response (Pydantic)
│   ├── requirements.txt
│   └── static/               # Frontend PWA
│       ├── index.html
│       ├── app.js             # IndexedDB, chat, sync, STT/TTS browser
│       ├── styles.css
│       ├── sw.js               # Service worker (cache app-shell)
│       └── manifest.json
├── esp32/                    # Starting point firmware (lihat catatan di bawah)
├── tests/                    # Test otomatis (pytest)
├── .env.example
├── .replit / pytest.ini
└── README.md (file ini)
```

## Menjalankan Secara Lokal

```bash
cd ai-smart-glasses
python3 -m venv .venv && source .venv/bin/activate    # atau .venv\Scripts\activate di Windows
pip install -r server/requirements.txt
cp .env.example .env
# edit .env — minimal isi LLM_API_KEY jika ingin mode online AI benar-benar menjawab

python3 -m uvicorn server.main:app --reload --port 8000
```

Buka `http://localhost:8000` — itu sudah menyajikan frontend PWA sekaligus API di server yang sama.

**Tanpa mengisi `.env` sama sekali**, server tetap bisa dijalankan (mode demo: penyimpanan di memori, hilang saat restart) — cocok untuk uji coba cepat, tapi akan tampil peringatan jelas di log & di `GET /health`.

## Menjalankan Test

```bash
pip install -r server/requirements.txt   # sudah termasuk pytest
pytest
```

Test-test ini memakai mode demo (in-memory) dan AI provider yang di-stub (tidak memanggil API sungguhan), jadi bisa langsung jalan tanpa database atau API key asli.

## Database (PostgreSQL)

Pakai layanan gratis seperti [Supabase](https://supabase.com) atau [Neon](https://neon.tech) — salin *connection string*-nya ke `DATABASE_URL` di `.env`. Skema (`server/schema.sql`) otomatis diterapkan saat server pertama kali start, jadi tidak perlu migrasi manual.

## AI Online

Memakai **rantai fallback** 3 provider yang kompatibel OpenAI Chat Completions API, dicoba berurutan: **OpenRouter → Z.ai → NVIDIA**. Isi minimal satu `*_API_KEY` di `.env` — provider tanpa key otomatis dilewati, dan kalau satu provider gagal (timeout/rate limit/error), sistem otomatis lanjut ke provider berikutnya sebelum permintaan chat benar-benar dianggap gagal.

| Provider | Env var key | Default model |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | `z-ai/glm-5.2:free` |
| Z.ai | `ZAI_API_KEY` | `glm-4.5-flash` |
| NVIDIA | `NVIDIA_API_KEY` | `nvidia/nemotron-3.5-lightning-30b-a3b` |

`LLM_PROVIDER` di `.env` hanya label referensi/log — urutan rantai fallback selalu tetap OpenRouter → Z.ai → NVIDIA berapa pun nilainya.

## AI Offline (Ollama)

1. Install [Ollama](https://ollama.com) di perangkat yang sama dengan browser/HP yang dipakai (karena browser memanggil `http://127.0.0.1:11434` langsung).
2. `ollama pull llama3.2:3b` (atau model lain — sesuaikan `OLLAMA_MODEL` di `.env` dan di `server/static/app.js`, cari `llama3.2:3b`).
3. Saat koneksi internet mati, aplikasi otomatis mencoba memanggil Ollama lokal, menyimpan hasilnya di IndexedDB, lalu menyinkronkannya ke server begitu online kembali.

**Keterbatasan yang jujur perlu disebutkan:** memanggil `127.0.0.1:11434` dari browser hanya berfungsi kalau Ollama berjalan di perangkat yang sama dengan yang membuka halaman ini (mis. laptop membuka `localhost:8000` dan Ollama juga di laptop itu). Untuk kacamata/ESP32 fisik yang tidak menjalankan Ollama sendiri, mode offline butuh strategi lain (mis. hub lokal di jaringan yang sama) — di luar cakupan yang bisa diverifikasi di sandbox ini.

## Deploy ke Replit

1. Buat Repl baru, upload isi folder ini (atau import dari GitHub).
2. Di tab **Secrets**, isi `DATABASE_URL`, `DEVICE_SIGNING_SECRET`, `LLM_API_KEY`, dst. (jangan taruh di `.env` yang ter-commit).
3. Klik **Run** — `.replit` sudah mengatur perintah start otomatis.

## Deploy ke Render.com

Render butuh kode kamu ada di repo Git (GitHub/GitLab) — tidak bisa upload zip langsung. Kalau belum punya akun GitHub, buat dulu di [github.com](https://github.com) (gratis).

1. **Push kode ke GitHub** — di folder proyek, jalankan:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   ```
   Buat repo baru di GitHub (klik "+" → "New repository", jangan centang "Add README"), lalu jalankan perintah `git remote add origin ...` dan `git push` yang ditampilkan GitHub setelah repo dibuat.

2. **Buat Blueprint di Render** — login ke [render.com](https://render.com) (bisa langsung pakai akun GitHub, tidak perlu kartu kredit untuk free tier), klik **New +** → **Blueprint**, pilih repo yang baru di-push. Render otomatis membaca `render.yaml` yang sudah ada di proyek ini dan mengisi konfigurasi build/start-nya sendiri.

3. **Isi Secrets** — sebelum/sesudah deploy pertama, buka tab **Environment** di service-nya, isi minimal:
   - `DATABASE_URL` (opsional — kosongkan dulu untuk mode demo, isi nanti kalau sudah bikin database di Supabase/Neon)
   - `DEVICE_SIGNING_SECRET` (generate: `python -c "import secrets; print(secrets.token_hex(32))"`)
   - Minimal satu dari `OPENROUTER_API_KEY` / `ZAI_API_KEY` / `NVIDIA_API_KEY`

4. **Deploy** — klik **Create Blueprint Instance** / **Deploy**. Tunggu build selesai (1-3 menit), lalu Render memberi URL publik seperti `https://ai-smart-glasses.onrender.com` — itu sudah bisa dipakai langsung, termasuk oleh ESP32 (ganti `API_BASE_URL` di `esp32/include/config.h` dengan URL ini).

**Catatan free tier Render:** service otomatis "tidur" setelah 15 menit tidak ada trafik, dan permintaan pertama setelah itu akan lambat (~30-50 detik) sampai dia bangun lagi. Ini normal untuk free tier, bukan bug. Setiap kamu `git push` perubahan baru, Render otomatis re-deploy sendiri.

## Firmware ESP32

`esp32/src/main.cpp` adalah **starting point**, bukan implementasi penuh — sudah mencakup koneksi Wi-Fi, registrasi perangkat anonim, dan pemanggilan `/api/chat`. Yang **belum** diimplementasikan (butuh perangkat keras fisik untuk dikembangkan & diuji, di luar cakupan yang bisa dikerjakan tanpa hardware): capture mikrofon (I2S) → speech-to-text, dan text-to-speech → speaker. Komentar di dalam file menjelaskan persis di mana kode ini perlu disambungkan ke driver audio kamu.

## Bandingkan dengan Proyek Lama (`aismart.zip`)

| | Proyek lama | Proyek ini |
|---|---|---|
| Identitas perangkat | 1 token global untuk semua | Token unik per perangkat, anonim, bisa dirotasi |
| Penyimpanan riwayat | Tidak ada | PostgreSQL (dengan fallback demo mode) |
| Mode offline | Tidak ada | Ollama lokal + sync otomatis saat online kembali |
| Frontend | HTML statis biasa | PWA (installable, IndexedDB, service worker) |
| Provider AI | Terkunci ke provider tertentu | Generic OpenAI-compatible via env var |
| Test otomatis | Tidak ada | `pytest` (auth, chat, sync, idempotency) |

File `.env` lama di `aismart.zip` **tidak disertakan/disalin** ke proyek ini karena berisi kemungkinan API key asli — isi ulang secara manual di `.env` proyek baru ini.
