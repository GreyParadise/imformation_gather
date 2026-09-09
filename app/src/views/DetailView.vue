<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, openExternal, timeAgo } from '../api'
import { feedStore } from '../store'

const route = useRoute()
const item = ref(feedStore.items.get(Number(route.params.id)) || null)
const err = ref('')

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
    <img v-if="item.cover" class="hero" :src="item.cover" referrerpolicy="no-referrer" @error="$event.target.remove()" alt="" />
    <div v-if="item.summary" class="summary-box">{{ item.summary }}</div>
    <div v-if="item.tags?.length" class="tags">
      <span v-for="t in item.tags" :key="t" class="t">#{{ t }}</span>
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
    <button class="btn" @click="openExternal(item.url)">阅读原文 ↗</button>
    <button class="btn ghost" style="margin-top:10px" @click="$router.back()">返回</button>
  </div>
  <div v-else class="empty">{{ err || '加载中…' }}</div>
</template>
