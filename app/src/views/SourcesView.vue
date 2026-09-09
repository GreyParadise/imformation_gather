<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, apiSend } from '../api'

const list = ref([])
const cats = ref([])
const loading = ref(true)
const err = ref('')
const form = reactive({ url: '', name: '', category: 'tech_ai', catName: '', mode: 'news' })
const addMsg = reactive({ ok: false, text: '' })
const adding = ref(false)
const testResult = ref(null)

async function load() {
  loading.value = true
  err.value = ''
  try {
    const [s, c] = await Promise.all([api('/api/sources'), api('/api/categories')])
    list.value = s.sources
    cats.value = c.categories
  } catch (e) {
    err.value = e.message
  }
  loading.value = false
}
onMounted(load)

const grouped = computed(() => {
  const g = {}
  for (const s of list.value) (g[s.category] ||= []).push(s)
  return g
})
const catNameOf = (key) => cats.value.find(c => c.key === key)?.name || key

async function toggle(s) {
  try {
    await apiSend(`/api/sources/${s.id}`, 'PATCH', { enabled: s.enabled ? 0 : 1 })
    s.enabled = s.enabled ? 0 : 1
  } catch (e) { err.value = e.message }
}

async function remove(s) {
  if (!confirm(`删除「${s.name}」及其全部已采文章？`)) return
  try {
    await apiSend(`/api/sources/${s.id}`, 'DELETE', {})
    load()
  } catch (e) { err.value = e.message }
}

async function test() {
  testResult.value = null
  addMsg.ok = false
  addMsg.text = '测试中…'
  try {
    const d = await apiSend('/api/sources/test', 'POST', { url: form.url })
    testResult.value = d
    addMsg.text = `✓ 《${d.feed_title || '未命名'}》可解析，共 ${d.count} 条`
    addMsg.ok = true
  } catch (e) {
    addMsg.text = '✗ ' + e.message
  }
}

async function add() {
  adding.value = true
  addMsg.ok = false
  addMsg.text = '添加中（服务端会先验证源）…'
  try {
    const payload = { url: form.url.trim(), name: form.name.trim(), mode: form.mode }
    if (form.catName.trim()) {
      payload.category = 'custom_' + Date.now().toString(36)
      payload.category_name = form.catName.trim()
    } else {
      payload.category = form.category
    }
    await apiSend('/api/sources', 'POST', payload)
    addMsg.text = '✓ 已添加，30 分钟内自动采集'
    addMsg.ok = true
    form.url = ''; form.name = ''; form.catName = ''
    testResult.value = null
    load()
  } catch (e) {
    addMsg.text = '✗ ' + e.message
  }
  adding.value = false
}
</script>

<template>
  <div class="sources">
    <div v-if="loading" class="loading">加载中…</div>
    <div v-if="err" class="err" style="padding:0 4px 10px">{{ err }}</div>
    <template v-for="(group, cat) in grouped" :key="cat">
      <div class="src-group-title">{{ catNameOf(cat) }}（{{ group.length }}）</div>
      <div v-for="s in group" :key="s.id" class="src-row" :style="s.enabled ? '' : 'opacity:.45'">
        <div class="info">
          <div class="nm">{{ s.name }} <span v-if="s.mode === 'subscription'" class="tagmini">更新订阅</span></div>
          <div class="u">{{ s.url }}</div>
        </div>
        <span class="st" :class="s.health">{{ { ok: '正常', degraded: '波动', failing: '频繁失败' }[s.health] || s.health }}</span>
        <span class="tagmini">{{ s.article_count }} 篇</span>
        <button :title="s.enabled ? '暂停' : '启用'" @click="toggle(s)">{{ s.enabled ? '⏸' : '▶️' }}</button>
        <button title="删除" @click="remove(s)">🗑</button>
      </div>
    </template>

    <div class="addbox">
      <h3>➕ 添加订阅源</h3>
      <input v-model="form.url" placeholder="RSS 链接（公众号/B站/起点等见下方提示）" />
      <input v-model="form.name" placeholder="名称（留空自动取订阅源标题）" />
      <div class="row">
        <select v-model="form.category">
          <option v-for="c in cats" :key="c.key" :value="c.key">{{ c.name }}</option>
        </select>
        <input v-model="form.catName" placeholder="或新建分类名" style="margin-bottom:10px" />
      </div>
      <select v-model="form.mode">
        <option value="news">资讯（去重聚类 + AI 摘要）</option>
        <option value="subscription">更新订阅（UP主/作者章回直读，不做摘要）</option>
      </select>
      <p class="hint">无 RSS 的网站（微信公众号/B站UP主/起点作者）建议先用 RSSHub 生成 RSS 链接再粘贴；自建可参考 github.com/DIYgod/RSSHub。</p>
      <div class="row">
        <button class="btn ghost" @click="test">试抓</button>
        <button class="btn" :disabled="adding || !form.url" @click="add">添加</button>
      </div>
      <div v-if="addMsg.text" :class="addMsg.ok ? 'msg-ok' : 'err'">{{ addMsg.text }}</div>
      <div v-if="testResult" style="margin-top:10px">
        <div v-for="s in testResult.samples" :key="s.url" class="src-row">
          <div class="info">
            <div class="nm" style="font-weight:400">{{ s.title }}</div>
            <div class="u">{{ s.published }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
