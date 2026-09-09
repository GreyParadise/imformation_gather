<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
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

async function loadCats() {
  try {
    const d = await api('/api/categories')
    categories.value = [{ key: '', name: '全部' }, ...d.categories]
  } catch { /* ignore */ }
}

async function load(reset = false) {
  if (loading.value || (!reset && done.value)) return
  loading.value = true
  error.value = ''
  if (reset) { records.value = []; cursor.value = null; done.value = false }
  try {
    const d = await api('/api/news', { category: active.value, before: cursor.value, size: 30 })
    feedStore.add(d.records)
    records.value = [...records.value, ...d.records]
    cursor.value = d.next_cursor
    done.value = !d.next_cursor
  } catch (e) {
    error.value = e.message
  }
  loading.value = false
}

function pick(k) {
  active.value = k
  load(true)
}

function onScroll() {
  const el = document.scrollingElement || document.documentElement
  if (el.scrollHeight - el.scrollTop - el.clientHeight < innerHeight) load()
}

onMounted(() => {
  loadCats()
  load(true)
  addEventListener('scroll', onScroll)
})
onBeforeUnmount(() => removeEventListener('scroll', onScroll))

defineExpose({ load })
</script>

<template>
  <div>
    <div class="chips">
      <span
        v-for="c in categories" :key="c.key"
        class="chip" :class="{ on: active === c.key }"
        @click="pick(c.key)"
      >{{ c.name }}</span>
    </div>
    <div class="masonry">
      <NewsCard v-for="r in records" :key="r.id" :item="r" />
    </div>
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="empty">
      {{ error }}<br />
      <button class="btn small ghost" style="margin-top:12px" @click="load()">重试</button>
    </div>
    <div v-else-if="!records.length" class="empty">
      暂无内容<br />后端采集/摘要任务运行后会自动出现
    </div>
    <div v-else-if="done" class="empty" style="padding:20px">· 到底了 ·</div>
  </div>
</template>
