<script setup>
import { ref } from 'vue'
import { timeAgo } from '../api'

defineProps({ item: { type: Object, required: true } })
const imgOk = ref(true)
</script>

<template>
  <article class="card" @click="$router.push(`/item/${item.id}`)">
    <img
      v-if="item.cover && imgOk"
      class="cover"
      :src="item.cover"
      loading="lazy"
      referrerpolicy="no-referrer"
      @error="imgOk = false"
      alt=""
    />
    <div class="body">
      <div class="title">{{ item.title }}</div>
      <div v-if="item.summary" class="summary">{{ item.summary }}</div>
      <div class="meta">
        <span class="src">{{ item.source_name }}</span>
        <span>{{ timeAgo(item.published_at) }}</span>
        <span v-if="item.cluster_size > 1" class="hot">{{ item.cluster_size }} 家报道</span>
      </div>
      <div v-if="item.tags?.length" style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap">
        <span v-for="t in item.tags.slice(0, 3)" :key="t" class="tagmini">{{ t }}</span>
      </div>
    </div>
  </article>
</template>
