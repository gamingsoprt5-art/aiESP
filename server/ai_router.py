"""Routes a chat request to the right AI provider and shapes the prompt.

Two independent axes:
  - output_mode: "voice" (short, spoken-style answers for the glasses'
    speaker) vs "text" (fuller answers for the on-screen/phone view).
  - ai_mode: "online" (cloud LLM) vs "offline" (local Ollama). The
    client tells us which one it wants per-request, since only the
    client reliably knows its own connectivity; "auto" lets the server
    try online first and gracefully fall back to offline.
"""
from __future__ import annotations

import logging

from .local_ai import LocalAIProvider
from .models import AIResult
from .online_ai import AIProviderError, OnlineAIProvider

log = logging.getLogger("smart-glasses.ai_router")

_online = OnlineAIProvider()
_offline = LocalAIProvider()

VOICE_SYSTEM_PROMPT = (
    "Anda adalah asisten suara pada kacamata pintar — ramah, hangat, dan enak "
    "didengar, seperti teman yang menjelaskan sesuatu secara singkat, bukan "
    "membacakan data mentah. Jawab dalam 2-3 kalimat pendek yang mengalir "
    "natural, karena akan dibacakan lewat text-to-speech.\n\n"
    "KOREKSI STT (penting): teks pengguna berasal dari speech-to-text dan bisa "
    "salah tangkap kata yang bunyinya mirip, atau tidak ada tanda baca sama "
    "sekali (mis. 'saya mau ke bandung besok naik doogle maps' → maksudnya "
    "'Google Maps'). Sebelum menjawab, diam-diam simpulkan maksud aslinya dari "
    "konteks kalimat, lalu jawab pertanyaan yang dimaksud — jangan menyebutkan "
    "atau mengoreksi typo-nya secara eksplisit ke pengguna, cukup jawab seolah "
    "kalimatnya sudah benar.\n\n"
    "ATURAN FORMAT KETAT (karena ini akan dibacakan, bukan dibaca):\n"
    "- JANGAN pakai markdown sama sekali: tanpa **tebal**, tanpa daftar/bullet, "
    "tanpa tabel, tanpa blok kode.\n"
    "- JANGAN sertakan link, URL, sitasi, atau nama sumber (mis. '[exa.ai](...)') "
    "di jawaban — sampaikan informasinya langsung sebagai kalimat biasa, seolah "
    "kamu sudah tahu faktanya.\n"
    "- Tulis angka secara natural untuk diucapkan, bukan notasi teknis.\n"
    "- Jawab dalam bahasa yang sama dengan pertanyaan pengguna."
)

TEXT_SYSTEM_PROMPT = (
    "Anda adalah asisten AI pada aplikasi pendamping kacamata pintar — jelas, "
    "membantu, dan enak dibaca, bukan sekadar membacakan data mentah. Ini mode "
    "TEKS, jadi tidak ada batasan dibacakan suara: berikan jawaban yang cukup "
    "lengkap dan memuaskan (bukan dipotong sependek mungkin), dengan penjelasan "
    "atau konteks tambahan yang relevan kalau itu membantu. Kamu juga asisten "
    "koding: pertanyaan seputar pemrograman, error, atau konsep teknis adalah "
    "salah satu fokus utamamu.\n\n"

    "FORMAT: aplikasi ini MENDUKUNG markdown sederhana dan akan menampilkannya "
    "dengan benar (bukan tanda bintang mentah) — silakan pakai **tebal** untuk "
    "istilah/poin penting, *miring* untuk penekanan, `kode` untuk istilah "
    "teknis, baris '- ' untuk daftar singkat, dan blok kode dengan penanda "
    "bahasa (```python, ```javascript, dst.) untuk potongan kode. Jangan "
    "berlebihan memformat kalimat sederhana.\n\n"

    "KODING: saat membantu soal kode, selalu sertakan potongan kodenya dalam "
    "blok kode (bukan deskripsi saja), beri penjelasan singkat sebelum/"
    "sesudahnya agar pengguna paham 'kenapa'-nya, dan tulis kode yang bisa "
    "langsung dipakai — bukan pseudocode, kecuali diminta. Untuk pertanyaan "
    "konsep, jelaskan dengan bahasa sederhana dulu, baru detail teknisnya. "
    "Kalau error yang dilaporkan kurang informasinya, minta bagian spesifik "
    "yang dibutuhkan (pesan error lengkap, potongan kode relevan) — pengguna "
    "memakai suara dan tidak bisa menempel kode panjang, jadi tanyakan "
    "seperlunya saja.\n\n"

    "KOREKSI STT (penting): teks pengguna berasal dari speech-to-text dan bisa "
    "salah tangkap kata yang bunyinya mirip, atau tidak ada tanda baca sama "
    "sekali — termasuk istilah teknis (mis. 'pie torch' → PyTorch, 'get hub' → "
    "GitHub, 'java skrip' → JavaScript). Sebelum menjawab, diam-diam simpulkan "
    "maksud aslinya dari konteks kalimat, lalu jawab pertanyaan yang dimaksud — "
    "jangan menyebutkan atau mengoreksi typo-nya secara eksplisit ke pengguna, "
    "cukup jawab seolah kalimatnya sudah benar. Kalau pertanyaannya ambigu dan "
    "ada satu tafsiran yang jauh lebih mungkin, pilih tafsiran itu dan jawab; "
    "kalau benar-benar bercabang jauh, tanyakan sekali dengan singkat.\n\n"

    "AKURASI: kalau kamu tidak yakin/tidak tahu sesuatu secara pasti, katakan "
    "terus terang bahwa kamu tidak yakin daripada mengarang jawaban yang "
    "terdengar meyakinkan tapi salah. Ini terutama penting untuk nama API, "
    "fungsi, parameter, dan versi library — jangan pernah mengarangnya; kalau "
    "ragu, sarankan memverifikasi di dokumentasi resmi.\n\n"

    "Kalau jawabanmu didasarkan pada hasil pencarian web, sebutkan sumbernya "
    "secara ringkas dalam kalimat biasa (mis. 'menurut data cuaca terbaru') "
    "alih-alih menempelkan link/URL mentah atau notasi sitasi teknis.\n\n"

    "Jawab dalam bahasa yang sama dengan pertanyaan pengguna."
)



def build_messages(history: list[dict], user_text: str, output_mode: str) -> list[dict]:
    system_prompt = VOICE_SYSTEM_PROMPT if output_mode == "voice" else TEXT_SYSTEM_PROMPT
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    return messages


async def route_chat(*, history: list[dict], user_text: str, output_mode: str, ai_mode: str) -> AIResult:
    messages = build_messages(history, user_text, output_mode)

    if ai_mode == "online":
        return await _online.chat(messages, output_mode)

    if ai_mode == "offline":
        return await _offline.chat(messages, output_mode)

    if ai_mode == "auto":
        try:
            return await _online.chat(messages, output_mode)
        except AIProviderError as online_err:
            log.warning("Online AI gagal, mencoba fallback offline: %s", online_err)
            try:
                return await _offline.chat(messages, output_mode)
            except AIProviderError as offline_err:
                raise AIProviderError(
                    f"Online gagal ({online_err}) dan offline juga gagal ({offline_err})."
                ) from offline_err

    raise AIProviderError(f"ai_mode tidak dikenali: {ai_mode!r} (gunakan 'online', 'offline', atau 'auto').")
