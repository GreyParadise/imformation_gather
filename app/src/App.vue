<script setup>
import { reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, config, saveConfig } from './api'

const route = useRoute()
const showCfg = ref(false)
const cfg = reactive({ url: config.url, key: config.key })
const cfgMsg = ref('')
const connected = ref(null)

watch(showCfg, (v) => {
  if (v) { cfg.url = config.url; cfg.key = config.key; cfgMsg.value = ''; connected.value = null }
})

async function testConn() {
  saveConfig({ url: cfg.url.trim(), key: cfg.key.trim() })
  connected.value = null
  try {
    await api('/api/health')
    connected.value = true
  } catch (e) {
    connected.value = false
    cfgMsg.value = e.message
  }
}

function save() {
  saveConfig({ url: cfg.url.trim(), key: cfg.key.trim() })
  showCfg.value = false
  location.reload()
}

const needCfg = () => !config.url && !import.meta.env.DEV
</script>

<template>
  <header class="topbar">
    <h1>{{ route.name === 'item' ? '文章详情' : route.name === 'sources' ? '订阅源管理' : '资讯快看' }}</h1>
    <button v-if="route.name === 'news'" class="icon-btn" title="刷新" @click="$refs.rv?.load(true)">↻</button>
    <button v-if="route.name === 'news'" class="icon-btn" @click="$router.push('/sources')">📡</button>
    <button class="icon-btn" @click="showCfg = true">⚙️</button>
  </header>

  <router-view ref="rv" />

  <nav class="tabbar">
    <router-link to="/"><span class="ico">📰</span>资讯</router-link>
    <router-link to="/sources"><span class="ico">📡</span>订阅源</router-link>
    <a @click.prevent="showCfg = true"><span class="ico">⚙️</span>设置</a>
  </nav>

  <div v-if="showCfg" class="modal-mask" @click.self="showCfg = false">
    <div class="modal">
      <h3>服务器设置</h3>
      <label>API 地址（留空=同源，开发模式）</label>
      <input v-model="cfg.url" placeholder="https://your-tunnel.trycloudflare.com" />
      <label>App Key</label>
      <input v-model="cfg.key" type="password" placeholder="后端 .env 中的 APP_KEY" />
      <div v-if="connected === true" class="msg-ok">✓ 连接成功</div>
      <div v-if="connected === false" class="err">✗ {{ cfgMsg }}</div>
      <div class="actions">
        <button class="btn ghost" @click="testConn">测试连接</button>
        <button class="btn" @click="save">保存</button>
      </div>
    </div>
  </div>

  <div v-if="needCfg() && !showCfg" class="modal-mask">
    <div class="modal">
      <h3>首次使用</h3>
      <p style="font-size:13.5px;color:var(--text-2);margin-bottom:6px">请填写后端 API 地址与 App Key（后端 .env 中的 APP_KEY）。</p>
      <label>API 地址</label>
      <input v-model="cfg.url" placeholder="https://..." />
      <label>App Key</label>
      <input v-model="cfg.key" type="password" />
      <div class="actions">
        <button class="btn ghost" @click="testConn">测试连接</button>
        <button class="btn" @click="save">保存</button>
      </div>
      <div v-if="connected === true" class="msg-ok">✓ 连接成功，请点保存</div>
      <div v-if="connected === false" class="err">✗ {{ cfgMsg }}</div>
    </div>
  </div>
</template>
