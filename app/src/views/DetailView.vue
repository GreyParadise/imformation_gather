<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, mediaUrl, openExternal, rewriteReaderHtml, timeAgo } from '../api'
import { feedStore } from '../store'

const route = useRoute()
const router = useRouter()
const item = ref(feedStore.items.get(Number(route.params.id)) || null)
const err = ref('')
const reader = ref(null)
const reading = ref(false)
const readErr = ref('')

const coverSrc = computed(() => mediaUrl(item.value || {}))

function pickTag(t) {
  feedStore.tag = t
  feedStore.query = ''
  router.push('/')
}

async function quickRead() {
  reading.value = true
  readErr.value = ''
  try {
    const d = await api(`/api/read/${route.params.id}`)
    if (d.error) {
      readErr.value = d.error === 'extract_failed' ? '该站点正文提取失败，请用原文打开' : '中转失败，请用原文打开'
    } else {
      reader.value = d
    }
  } catch (e) {
    readErr.value = e.message
  }
  reading.value = false
}

onMounted(async () => {
  try {
    const d = await api(`/api/news/item/${route.params.id}`)
    item.value = { ...item.value, ...d }
  } catch (e) {
    err.value = e.message
  }
})
</script>

<template>
  <div v-if="item" class="detail">
    <h2>{{ item.title }}</h2>
    <div class="meta">
      <span style="color:var(--accent)">{{ item.source_name }}</span>
      <span>{{ timeAgo(item.published_at) }}</span>
      <span v-if="item.cluster_size > 1">{{ item.cluster_size }} 家媒体报道</span>
    </div>
    <img v-if="coverSrc" class="hero" :src="coverSrc" referrerpolicy="no-referrer" @error="$event.target.remove()" alt="" />
    <div v-if="item.summary" class="summary-box">{{ item.summary }}</div>
    <div v-if="item.tags?.length" class="tags">
      <span v-for="t in item.tags" :key="t" class="t" @click="pickTag(t)">#{{ t }}</span>
    </div>
    <p v-if="item.excerpt" class="excerpt">{{ item.excerpt }}…</p>
    <div v-if="item.related?.length" class="related">
      <h3>同一事件的其他来源</h3>
      <div v-for="(rel, i) in item.related" :key="i" class="rel" @click="openExternal(rel.url)">
        <small>{{ rel.source_name }}</small>
        <span style="flex:1">{{ rel.title }}</span>
        <small>原文 ↗</small>
      </div>
    </div>

    <div v-if="reader" class="reader">
      <div class="reader-head">
        <b>⚡ 极速阅读</b>
        <small>{{ reader.source === 'rss' ? 'RSS 全文' : reader.source === 'web_partial' ? '原站正文（可能不全）' : '原站正文' }} · 后端中转</small>
      </div>
      <div class="reader-body" v-html="rewriteReaderHtml(reader.html)" />
    </div>
    <div v-if="readErr" class="err" style="margin:8px 0">{{ readErr }}</div>

    <div class="row-btns">
      <button v-if="!reader" class="btn ghost" :disabled="reading" @click="quickRead">{{ reading ? '加载中…' : '⚡ 极速阅读' }}</button>
      <button class="btn" @click="openExternal(item.url)">打开原文 ↗</button>
    </div>
    <button class="btn ghost" style="margin-top:10px" @click="$router.back()">返回</button>
  </div>
  <div v-else class="empty">{{ err || '加载中…' }}</div>
</template>

<style scoped>
.row-btns { display: flex; gap: 10px; }
.row-btns .btn { flex: 1; }
.reader {
  margin: 6px 0 14px; padding: 14px; background: var(--card);
  border: 1px solid var(--line); border-radius: 12px;
}
.reader-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 10px; font-size: 13px; color: var(--text-2); }
.reader-head b { color: var(--accent); font-size: 14px; }
.reader-body { font-size: 15px; line-height: 1.85; color: var(--text); }
</style>

<style>
.reader-body p { margin: 0 0 12px; }
.reader-body img { max-width: 100%; height: auto; border-radius: 10px; margin: 6px 0 12px; display: block; }
.reader-body h2, .reader-body h3, .reader-body h4 { margin: 16px 0 8px; font-size: 16px; }
.reader-body ul, .reader-body ol { padding-left: 22px; margin: 0 0 12px; }
.reader-body blockquote { border-left: 3px solid var(--accent); margin: 0 0 12px; padding: 4px 12px; color: var(--text-2); }
.reader-body figure { margin: 0 0 12px; }
.reader-body figcaption, .reader-body time { font-size: 12px; color: var(--text-3); }
.reader-body a { color: var(--accent); }
</style>
