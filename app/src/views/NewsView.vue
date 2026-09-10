<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { feedStore } from '../store'
import NewsCard from '../components/NewsCard.vue'

const categories = ref([{ key: '', name: '全部' }])
const active = ref('')
const records = ref([])
const cursor = ref(null)
const loading = ref(false)
const done = ref(false)
const error = ref('')
const total = ref(0)

const sources = ref([])
const hotTags = ref([])
const qInput = ref('')
const sourceSel = ref('')
let debounce = null

const filterTag = computed(() => feedStore.tag)
const hasFilter = computed(() => !!(feedStore.query || filterTag.value || sourceSel.value))

async function loadCats() {
  try {
    const d = await api('/api/categories')
    categories.value = [{ key: '', name: '全部' }, ...d.categories]
  } catch { /* ignore */ }
}
async function loadFacets() {
  try {
    const [s, t] = await Promise.all([api('/api/sources'), api('/api/tags')])
    sources.value = s.sources.filter(x => x.mode === 'news')
    hotTags.value = t.tags
  } catch { /* ignore */ }
}

async function load(reset = false) {
  if (loading.value || (!reset && done.value)) return
  loading.value = true
  error.value = ''
  if (reset) { records.value = []; cursor.value = null; done.value = false }
  try {
    const params = { category: active.value, before: cursor.value, size: 30 }
    if (feedStore.query) params.q = feedStore.query
    if (filterTag.value) params.tag = filterTag.value
    if (sourceSel.value) params.source = sourceSel.value
    const d = await api('/api/news', params)
    feedStore.add(d.records)
    records.value = [...records.value, ...d.records]
    cursor.value = d.next_cursor
    total.value = d.total ?? total.value
    done.value = !d.next_cursor
  } catch (e) {
    error.value = e.message
  }
  loading.value = false
}

function pick(k) { active.value = k; load(true) }
function onSearchInput() {
  clearTimeout(debounce)
  debounce = setTimeout(() => { feedStore.query = qInput.value.trim(); load(true) }, 450)
}
function clearSearch() { qInput.value = ''; feedStore.query = ''; load(true) }
function clearTag() { feedStore.tag = ''; load(true) }
function clearAll() { feedStore.tag = ''; feedStore.query = ''; qInput.value = ''; sourceSel.value = ''; load(true) }
function pickTag(t) { feedStore.tag = feedStore.tag === t ? '' : t; load(true) }

watch(filterTag, () => load(true))
watch(sourceSel, () => load(true))

function onScroll() {
  const el = document.scrollingElement || document.documentElement
  if (el.scrollHeight - el.scrollTop - el.clientHeight < innerHeight) load()
}

onMounted(() => {
  loadCats()
  loadFacets()
  load(true)
  addEventListener('scroll', onScroll)
})
onBeforeUnmount(() => {
  removeEventListener('scroll', onScroll)
  clearTimeout(debounce)
})

defineExpose({ load })
</script>

<template>
  <div>
    <div class="searchbar">
      <input v-model="qInput" type="search" placeholder="搜索标题 / 摘要 / 标签…" @input="onSearchInput" />
      <select v-model="sourceSel">
        <option value="">全部来源</option>
        <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
    </div>

    <div class="chips">
      <span v-for="c in categories" :key="c.key" class="chip" :class="{ on: active === c.key }" @click="pick(c.key)">{{ c.name }}</span>
    </div>

    <div v-if="!hasFilter && hotTags.length" class="tagbar">
      <span class="tb-label">热门</span>
      <span v-for="t in hotTags.slice(0, 12)" :key="t.name" class="tagchip" @click="pickTag(t.name)">{{ t.name }}</span>
    </div>

    <div v-if="hasFilter" class="filterbar">
      <span>筛选中：<b v-if="feedStore.query">🔍{{ feedStore.query }}</b><b v-if="filterTag">#{{ filterTag }}</b><b v-if="sourceSel">📡{{ sources.find(x=>x.id==sourceSel)?.name }}</b></span>
      <span class="fcount">{{ total }} 条</span>
      <button class="fclear" @click="clearAll">清除</button>
    </div>

    <div class="masonry">
      <NewsCard v-for="r in records" :key="r.id" :item="r" />
    </div>
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="empty">{{ error }}<br /><button class="btn small ghost" style="margin-top:12px" @click="load()">重试</button></div>
    <div v-else-if="!records.length" class="empty">{{ hasFilter ? '没有匹配的结果' : '暂无内容，稍后自动刷新' }}</div>
    <div v-else-if="done" class="empty" style="padding:20px">· 到底了 ·</div>
  </div>
</template>

<style scoped>
.searchbar { display: flex; gap: 8px; padding: 10px 12px 0; }
.searchbar input {
  flex: 1; padding: 9px 12px; border-radius: 10px; border: 1px solid var(--line);
  background: var(--card); color: var(--text); font-size: 14px;
}
.searchbar select {
  padding: 9px 10px; border-radius: 10px; border: 1px solid var(--line);
  background: var(--card); color: var(--text); font-size: 13px; max-width: 110px;
}
.tagbar { display: flex; gap: 8px; padding: 8px 12px 0; overflow-x: auto; scrollbar-width: none; white-space: nowrap; }
.tagbar::-webkit-scrollbar { display: none; }
.tb-label { color: var(--text-3); font-size: 12px; flex-shrink: 0; line-height: 26px; }
.tagchip {
  flex-shrink: 0; font-size: 12px; padding: 3px 10px; border-radius: 999px;
  background: var(--tag); color: var(--text-2); cursor: pointer;
}
.filterbar {
  display: flex; align-items: center; gap: 10px; margin: 8px 12px 0; padding: 8px 12px;
  background: var(--card); border: 1px solid var(--line); border-radius: 10px; font-size: 13px; color: var(--text-2);
}
.filterbar b { color: var(--accent); margin: 0 2px; }
.fcount { margin-left: auto; color: var(--text-3); }
.fclear { background: none; border: 1px solid var(--line); color: var(--text-2); border-radius: 8px; padding: 3px 10px; cursor: pointer; font-size: 12px; }
</style>
