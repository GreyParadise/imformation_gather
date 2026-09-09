<script setup>
import { onMounted, ref } from 'vue'
import { api, openExternal, timeAgo } from '../api'

const records = ref([])
const cursor = ref(null)
const loading = ref(false)
const done = ref(false)
const error = ref('')

async function load(reset = false) {
  if (loading.value || (!reset && done.value)) return
  loading.value = true
  error.value = ''
  if (reset) { records.value = []; cursor.value = null; done.value = false }
  try {
    const d = await api('/api/updates', { before: cursor.value, size: 30 })
    records.value = [...records.value, ...d.records]
    cursor.value = d.next_cursor
    done.value = !d.next_cursor
  } catch (e) {
    error.value = e.message
  }
  loading.value = false
}
onMounted(() => load(true))

defineExpose({ load })
</script>

<template>
  <div class="updates">
    <div v-for="r in records" :key="r.id" class="upd-row" @click="openExternal(r.url)">
      <div class="u-title">{{ r.title }}</div>
      <div class="u-meta">
        <span class="src">{{ r.source_name }}</span>
        <span>{{ timeAgo(r.published_at) }}</span>
        <span class="go">直达 ↗</span>
      </div>
    </div>
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="empty">{{ error }}</div>
    <div v-else-if="!records.length" class="empty">
      还没有订阅更新<br />
      去「订阅源」页添加 B站UP主 / 公众号 / 起点作者等源，模式选「更新订阅」
    </div>
    <div v-else-if="done" class="empty" style="padding:20px">· 到底了 ·</div>
  </div>
</template>

<style scoped>
.updates { padding: 12px 12px calc(80px + env(safe-area-inset-bottom)); }
.upd-row {
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; margin-bottom: 8px; cursor: pointer;
}
.upd-row:active { background: var(--card-hover); }
.u-title { font-size: 14.5px; font-weight: 600; line-height: 1.5; margin-bottom: 6px; }
.u-meta { display: flex; gap: 10px; font-size: 12px; color: var(--text-3); align-items: center; }
.u-meta .src { color: var(--accent); }
.u-meta .go { margin-left: auto; }
</style>
