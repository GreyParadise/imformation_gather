<script setup>
import { computed, ref } from 'vue'
import { mediaUrl, timeAgo } from '../api'
import { feedStore } from '../store'

const props = defineProps({ item: { type: Object, required: true } })
const imgOk = ref(true)
const coverSrc = computed(() => mediaUrl(props.item))

function pickTag(t) {
  feedStore.tag = t
  feedStore.query = ''
}
</script>

<template>
  <article class="card" :class="{ feat: item.cluster_size >= 3 }" @click="$router.push(`/item/${item.id}`)">
    <img
      v-if="coverSrc && imgOk"
      class="cover"
      :src="coverSrc"
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
        <span v-for="t in item.tags.slice(0, 3)" :key="t" class="tagmini" @click.stop="pickTag(t)">{{ t }}</span>
      </div>
    </div>
  </article>
</template>
