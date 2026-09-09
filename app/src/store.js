import { reactive } from 'vue'

export const feedStore = reactive({
  items: new Map(),
  add(records) {
    for (const r of records) this.items.set(r.id, r)
  }
})
