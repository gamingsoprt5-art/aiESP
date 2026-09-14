// ===================================================================
// AI Smart Glasses — frontend app logic
// Zero build step, zero external JS dependencies (Chart-free, framework-free)
// ===================================================================
'use strict';

const API_BASE = ''; // same-origin
const DB_NAME = 'smart_glasses_db';
const DB_VERSION = 1;

// ---------------------------------------------------------------
// IndexedDB helper (minimal, no external lib)
// ---------------------------------------------------------------
const Store = {
  _db: null,

  open() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('conversations')) {
          db.createObjectStore('conversations', { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains('messages')) {
          const ms = db.createObjectStore('messages', { keyPath: 'client_message_id' });
          ms.createIndex('by_conversation', 'conversation_id');
          ms.createIndex('by_synced', 'synced');
        }
        if (!db.objectStoreNames.contains('meta')) {
          db.createObjectStore('meta', { keyPath: 'key' });
        }
      };
      req.onsuccess = () => { this._db = req.result; resolve(this._db); };
      req.onerror = () => reject(req.error);
    });
  },

  tx(store, mode) { return this._db.transaction(store, mode).objectStore(store); },

  put(store, value) {
    return new Promise((resolve, reject) => {
      const r = this.tx(store, 'readwrite').put(value);
      r.onsuccess = () => resolve(value);
      r.onerror = () => reject(r.error);
    });
  },
  get(store, key) {
    return new Promise((resolve, reject) => {
      const r = this.tx(store, 'readonly').get(key);
      r.onsuccess = () => resolve(r.result || null);
      r.onerror = () => reject(r.error);
    });
  },
  getAll(store) {
    return new Promise((resolve, reject) => {
      const r = this.tx(store, 'readonly').getAll();
      r.onsuccess = () => resolve(r.result || []);
      r.onerror = () => reject(r.error);
    });
  },
  getAllByIndex(store, index, key) {
    return new Promise((resolve, reject) => {
      const r = this.tx(store, 'readonly').index(index).getAll(key);
      r.onsuccess = () => resolve(r.result || []);
      r.onerror = () => reject(r.error);
    });
  },
};

function toast(msg, isError) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isError ? ' error' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 2600);
}
function uuid() {
  return (crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8); return v.toString(16);
  }));
}

// ---------------------------------------------------------------
// App state
// ---------------------------------------------------------------
const App = {
  installationId: null,
  deviceId: null,
  deviceToken: null,
  conversationId: null,
  outputMode: 'voice',
  aiMode: 'auto',
  isOnline: navigator.onLine,
  lastPull: null,
  recognition: null,
  recording: false,

  async init() {
    await Store.open();

    this.installationId = localStorage.getItem('sg_installation_id');
    if (!this.installationId) {
      this.installationId = 'web-' + uuid();
      localStorage.setItem('sg_installation_id', this.installationId);
    }
    this.deviceId = localStorage.getItem('sg_device_id');
    this.deviceToken = localStorage.getItem('sg_device_token');
    this.lastPull = localStorage.getItem('sg_last_pull');

    if (!this.deviceToken) {
      await this.registerDevice();
    } else {
      document.getElementById('deviceLabel').textContent = 'perangkat #' + this.deviceId.slice(0, 8);
    }

    const savedConv = localStorage.getItem('sg_conversation_id');
    if (savedConv && await Store.get('conversations', savedConv)) {
      this.conversationId = savedConv;
      await this.renderConversation();
    }

    this.bindUI();
    this.updateNetStatus();
    this.refreshLocalAiStatus();

    window.addEventListener('online', () => { this.updateNetStatus(); this.syncNow(); });
    window.addEventListener('offline', () => this.updateNetStatus());
    setInterval(() => this.refreshLocalAiStatus(), 30000);
    if (this.isOnline) this.syncNow();
  },

  async registerDevice() {
    try {
      const res = await fetch(API_BASE + '/api/devices/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ installation_id: this.installationId, device_name: navigator.userAgent.slice(0, 60) }),
      });
      if (!res.ok) throw new Error('status ' + res.status);
      const data = await res.json();
      this.deviceId = data.device_id;
      this.deviceToken = data.device_token;
      localStorage.setItem('sg_device_id', this.deviceId);
      localStorage.setItem('sg_device_token', this.deviceToken);
      document.getElementById('deviceLabel').textContent = 'perangkat #' + this.deviceId.slice(0, 8);
    } catch (err) {
      document.getElementById('deviceLabel').textContent = 'belum terhubung ke server';
      console.warn('Registrasi perangkat gagal (mode offline murni):', err);
    }
  },

  authHeaders() {
    return this.deviceToken ? { 'Authorization': 'Device ' + this.deviceToken } : {};
  },

  bindUI() {
    document.querySelectorAll('#outputModeSeg .seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#outputModeSeg .seg-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.outputMode = btn.dataset.mode;
      });
    });
    document.querySelectorAll('#aiModeSeg .seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#aiModeSeg .seg-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.aiMode = btn.dataset.ai;
      });
    });

    const input = document.getElementById('textInput');
    document.getElementById('sendBtn').addEventListener('click', () => this.handleSend());
    input.addEventListener('keydown', e => { if (e.key === 'Enter') this.handleSend(); });

    const micBtn = document.getElementById('micBtn');
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      micBtn.disabled = true;
      micBtn.title = 'Pengenalan suara tidak didukung browser ini';
    } else {
      this.recognition = new SR();
      this.recognition.lang = 'id-ID';
      this.recognition.interimResults = false;
      this.recognition.maxAlternatives = 1;
      this.recognition.onresult = (e) => {
        const text = e.results[0][0].transcript;
        input.value = text;
        this.handleSend();
      };
      this.recognition.onend = () => { this.recording = false; micBtn.classList.remove('recording'); };
      this.recognition.onerror = () => { this.recording = false; micBtn.classList.remove('recording'); };
      micBtn.addEventListener('click', () => {
        if (this.recording) { this.recognition.stop(); return; }
        this.recording = true; micBtn.classList.add('recording');
        try { this.recognition.start(); } catch (_) {}
      });
    }
  },

  updateNetStatus() {
    this.isOnline = navigator.onLine;
    const pill = document.getElementById('netStatus');
    pill.className = 'status-pill ' + (this.isOnline ? 'ok' : 'off');
    pill.querySelector('span:last-child').textContent = this.isOnline ? 'Online' : 'Offline';
  },

  async refreshLocalAiStatus() {
    const pill = document.getElementById('aiStatus');
    const label = document.getElementById('aiStatusText');
    if (!this.isOnline) {
      pill.className = 'status-pill warn';
      label.textContent = 'Cek AI lokal…';
      try {
        const r = await fetch('http://127.0.0.1:11434/api/tags', { signal: AbortSignal.timeout(1500) });
        pill.className = 'status-pill ' + (r.ok ? 'ok' : 'off');
        label.textContent = r.ok ? 'AI Lokal Siap' : 'AI Lokal Tidak Terdeteksi';
      } catch (_) {
        pill.className = 'status-pill off';
        label.textContent = 'AI Lokal Tidak Terdeteksi';
      }
      return;
    }
    try {
      const res = await fetch(API_BASE + '/api/local-ai/status');
      const data = await res.json();
      pill.className = 'status-pill ok';
      label.textContent = 'Cloud AI';
      pill.title = data.available ? `AI lokal cadangan tersedia (${data.configured_model})` : 'AI lokal cadangan tidak terdeteksi di server';
    } catch (_) {
      pill.className = 'status-pill ok';
      label.textContent = 'Cloud AI';
    }
  },

  async ensureConversation() {
    if (this.conversationId) return this.conversationId;
    const id = uuid();
    const conv = { id, title: 'Percakapan baru', created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
    await Store.put('conversations', conv);
    this.conversationId = id;
    localStorage.setItem('sg_conversation_id', id);
    return id;
  },

  async handleSend() {
    const input = document.getElementById('textInput');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    document.getElementById('emptyHint').style.display = 'none';

    const conversationId = await this.ensureConversation();
    const clientMessageId = uuid();

    const userMsg = {
      client_message_id: clientMessageId, conversation_id: conversationId, role: 'user', content: text,
      output_mode: this.outputMode, ai_mode: this.aiMode, provider: 'client', model: null,
      created_at: new Date().toISOString(), synced: false,
    };
    await Store.put('messages', userMsg);
    this.appendBubble(userMsg);

    const typingId = this.appendTyping();

    try {
      const history = await this.recentHistory(conversationId);
      let assistantMsg;
      // Explicit mode selection wins over connectivity guessing: "Offline"
      // always calls the local Ollama instance directly from the browser
      // (works even when the internet is up — useful for testing), "Online"
      // always goes through the server, "Auto" picks based on navigator.onLine.
      if (this.aiMode === 'offline') {
        assistantMsg = await this.sendOfflineLocal(conversationId, text, history);
      } else if (this.aiMode === 'online') {
        assistantMsg = await this.sendOnline(conversationId, clientMessageId, text, history);
      } else if (this.isOnline && this.deviceToken) {
        assistantMsg = await this.sendOnline(conversationId, clientMessageId, text, history);
      } else {
        assistantMsg = await this.sendOfflineLocal(conversationId, text, history);
      }
      this.removeTyping(typingId);
      await Store.put('messages', assistantMsg);
      this.appendBubble(assistantMsg);
      if (this.outputMode === 'voice') this.speak(assistantMsg.content);
    } catch (err) {
      this.removeTyping(typingId);
      toast(err.message || 'Gagal mendapatkan jawaban AI.', true);
      console.error(err);
    }
  },

  async recentHistory(conversationId) {
    const all = await Store.getAllByIndex('messages', 'by_conversation', conversationId);
    all.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    return all.slice(-20).map(m => ({ role: m.role, content: m.content }));
  },

  // Wraps fetch with automatic recovery from an unrecognized device token:
  // if the server responds 401 (e.g. it lost its device table because it's
  // running in in-memory demo mode and got restarted), silently re-register
  // and retry the request once before giving up.
  async authedFetch(url, options = {}) {
    options.headers = { ...(options.headers || {}), ...this.authHeaders() };
    let res = await fetch(url, options);
    if (res.status === 401) {
      console.warn('Token perangkat ditolak server — mendaftar ulang otomatis…');
      localStorage.removeItem('sg_device_id');
      localStorage.removeItem('sg_device_token');
      this.deviceId = null;
      this.deviceToken = null;
      await this.registerDevice();
      options.headers = { ...(options.headers || {}), ...this.authHeaders() };
      res = await fetch(url, options);
    }
    return res;
  },

  async sendOnline(conversationId, clientMessageId, text, history) {
    const res = await this.authedFetch(API_BASE + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: conversationId, client_message_id: clientMessageId, text,
        output_mode: this.outputMode, ai_mode: this.aiMode, history: history.slice(0, -1),
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || ('Server error ' + res.status));
    }
    const data = await res.json();
    return {
      client_message_id: data.assistant_message.client_message_id, conversation_id: conversationId,
      role: 'assistant', content: data.assistant_message.content, output_mode: this.outputMode,
      ai_mode: data.assistant_message.ai_mode, provider: data.assistant_message.provider,
      model: data.assistant_message.model, created_at: data.assistant_message.created_at, synced: true,
    };
  },

  async sendOfflineLocal(conversationId, text, history) {
    // Directly call a local Ollama instance from the browser — works when
    // the phone/computer running this page can reach 127.0.0.1:11434.
    const systemPrompt = this.outputMode === 'voice'
      ? 'Anda adalah asisten suara pada kacamata pintar. Jawab singkat dan langsung, maksimal 2-3 kalimat pendek, tanpa format markdown. Jawab dalam bahasa yang sama dengan pertanyaan pengguna.'
      : 'Anda adalah asisten AI pada aplikasi pendamping kacamata pintar. Jawab dengan jelas dan terstruktur. Jawab dalam bahasa yang sama dengan pertanyaan pengguna.';
    const messages = [{ role: 'system', content: systemPrompt }, ...history];

    let res;
    try {
      res = await fetch('http://127.0.0.1:11434/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: 'llama3.2:3b', messages, stream: false }),
        signal: AbortSignal.timeout(45000),
      });
    } catch (err) {
      throw new Error('Sedang offline dan AI lokal (Ollama) tidak terjangkau di perangkat ini.');
    }
    if (!res.ok) throw new Error('AI lokal mengembalikan error ' + res.status);
    const data = await res.json();
    const content = ((data.message || {}).content || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim();
    if (!content) throw new Error('AI lokal mengembalikan jawaban kosong.');

    return {
      client_message_id: uuid(), conversation_id: conversationId, role: 'assistant', content,
      output_mode: this.outputMode, ai_mode: 'offline', provider: 'offline', model: 'llama3.2:3b',
      created_at: new Date().toISOString(), synced: false,
    };
  },

  speak(text) {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'id-ID';
    window.speechSynthesis.speak(u);
  },

  // ------------- sync (offline-created messages -> server) -------------
  async syncNow() {
    if (!this.deviceToken) { await this.registerDevice(); if (!this.deviceToken) return; }
    try {
      const allMsgs = await Store.getAll('messages');
      const pending = allMsgs.filter(m => !m.synced);
      if (pending.length) {
        const convCache = {};
        const items = [];
        for (const m of pending) {
          if (!convCache[m.conversation_id]) {
            convCache[m.conversation_id] = await Store.get('conversations', m.conversation_id);
          }
          items.push({
            client_message_id: m.client_message_id, conversation_id: m.conversation_id,
            conversation_title: (convCache[m.conversation_id] || {}).title || 'Percakapan',
            role: m.role, content: m.content, output_mode: m.output_mode,
            ai_mode: m.ai_mode === 'auto' ? 'online' : m.ai_mode, provider: m.provider || 'client',
            model: m.model, created_at: m.created_at,
          });
        }
        const res = await this.authedFetch(API_BASE + '/api/sync/push', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ items }),
        });
        if (res.ok) {
          for (const m of pending) { m.synced = true; await Store.put('messages', m); }
          toast('Riwayat offline tersinkron ke server.');
        }
      }

      const url = API_BASE + '/api/sync/pull' + (this.lastPull ? ('?since=' + encodeURIComponent(this.lastPull)) : '');
      const pullRes = await this.authedFetch(url, {});
      if (pullRes.ok) {
        const data = await pullRes.json();
        for (const m of data.messages) {
          await Store.put('messages', { ...m, synced: true });
        }
        this.lastPull = data.server_time;
        localStorage.setItem('sg_last_pull', this.lastPull);
        if (this.conversationId) await this.renderConversation();
      }
    } catch (err) {
      console.warn('Sync gagal, akan dicoba lagi nanti:', err);
    }
  },

  // ------------- rendering -------------
  async renderConversation() {
    const list = document.getElementById('messageList');
    list.innerHTML = '';
    const msgs = await Store.getAllByIndex('messages', 'by_conversation', this.conversationId);
    msgs.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    if (msgs.length) document.getElementById('emptyHint').style.display = 'none';
    msgs.forEach(m => this.appendBubble(m));
  },

  appendBubble(msg) {
    const list = document.getElementById('messageList');
    const row = document.createElement('div');
    row.className = 'msg-row ' + msg.role;
    const time = new Date(msg.created_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
    row.innerHTML = `
      <div>
        <div class="bubble">${escapeHtml(msg.content)}</div>
        <div class="msg-meta">
          <span>${time}</span>
          ${msg.role === 'assistant' ? `<span class="tag">${msg.ai_mode || ''}</span>` : ''}
        </div>
      </div>`;
    list.appendChild(row);
    document.getElementById('chatArea').scrollTop = document.getElementById('chatArea').scrollHeight;
  },

  appendTyping() {
    const list = document.getElementById('messageList');
    const id = 'typing-' + uuid();
    const row = document.createElement('div');
    row.className = 'msg-row assistant';
    row.id = id;
    row.innerHTML = `<div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>`;
    list.appendChild(row);
    document.getElementById('chatArea').scrollTop = document.getElementById('chatArea').scrollHeight;
    return id;
  },
  removeTyping(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  },
};

function escapeHtml(str) {
  return String(str || '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

App.init();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(err => console.warn('SW registration failed:', err));
  });
}
