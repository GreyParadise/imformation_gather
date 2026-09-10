<script setup>
import { reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, config, saveConfig, ui } from './api'

const route = useRoute()
const isDev = import.meta.env.DEV
const showCfg = ref(false)
const cfg = reactive({ url: config.url, key: config.key })
const cfgMsg = ref('')
const connected = ref(null)

function syncForm() {
  cfg.url = config.url
  cfg.key = config.key
  cfgMsg.value = ''
  connected.value = null
}

watch(showCfg, (v) => { if (v) syncForm() })

watch(() => ui.needKey, (v) => {
  if (v && !showCfg.value) { showCfg.value = true; syncForm(); connected.value = false; cfgMsg.value = '当前 App Key 缺失或错误，请重新填写' }
})

async function testConn() {
  saveConfig({ url: cfg.url.trim(), key: cfg.key.trim() })
  connected.value = null
  cfgMsg.value = ''
  try {
    await api('/api/stats')
    connected.value = true
  } catch (e) {
    connected.value = false
    cfgMsg.value = e.message
  }
}

async function save() {
  saveConfig({ url: cfg.url.trim(), key: cfg.key.trim() })
  showCfg.value = false
  ui.needKey = false
  try {
    await api('/api/stats')
  } catch { /* 忽略，下条会重载 */ }
  location.reload()
}

const needCfg = () => !config.key && !showCfg.value
</script>

<template>
  <header class="topbar">
    <h1>{{ route.name === 'item' ? '文章详情' : route.name === 'sources' ? '订阅源管理' : route.name === 'updates' ? '订阅更新' : '资讯快看' }}</h1>
    <button v-if="route.name === 'news'" class="icon-btn" title="刷新" @click="$refs.rv?.load(true)">↻</button>
    <button v-if="route.name === 'news'" class="icon-btn" @click="$router.push('/sources')">📡</button>
    <button class="icon-btn" @click="showCfg = true">⚙️</button>
  </header>

  <router-view ref="rv" />

  <nav class="tabbar">
    <router-link to="/"><span class="ico">📰</span>资讯</router-link>
    <router-link to="/updates"><span class="ico">📺</span>更新</router-link>
    <router-link to="/sources"><span class="ico">📡</span>订阅源</router-link>
    <a @click.prevent="showCfg = true"><span class="ico">⚙️</span>设置</a>
  </nav>

  <div v-if="showCfg" class="modal-mask" @click.self="showCfg = false">
    <div class="modal">
      <h3>服务器设置</h3>
      <label>API 地址{{ isDev ? '（开发模式同源，可留空）' : '' }}</label>
      <input v-model="cfg.url" placeholder="https://your-tunnel.trycloudflare.com" />
      <label>App Key</label>
      <input v-model="cfg.key" type="text" autocomplete="off" placeholder="后端 .env 中的 APP_KEY" />
      <div v-if="connected === true" class="msg-ok">✓ 鉴权通过</div>
      <div v-if="connected === false" class="err">✗ {{ cfgMsg }}</div>
      <div class="actions">
        <button class="btn ghost" @click="testConn">测试连接</button>
        <button class="btn" @click="save">保存</button>
      </div>
    </div>
  </div>

  <div v-else-if="needCfg()" class="modal-mask">
    <div class="modal">
      <h3>首次使用 · 请填写连接信息</h3>
      <p style="font-size:13px;color:var(--text-3);margin-bottom:8px">APK 内使用必须填写完整 API 地址（电脑双击 start.bat 后屏幕上显示的 https://xxx.trycloudflare.com），Key 存于本地按域名隔离。</p>
      <label>API 地址</label>
      <input v-model="cfg.url" placeholder="https://xxx.trycloudflare.com" />
      <label>App Key</label>
      <input v-model="cfg.key" type="text" autocomplete="off" placeholder="后端 .env 中的 APP_KEY" />
      <div v-if="connected === true" class="msg-ok">✓ 鉴权通过</div>
      <div v-if="connected === false" class="err">✗ {{ cfgMsg }}</div>
      <div class="actions">
        <button class="btn ghost" @click="testConn">测试连接</button>
        <button class="btn" @click="save">保存</button>
      </div>
    </div>
  </div>
</template>
