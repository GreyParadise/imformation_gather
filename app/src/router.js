import { createRouter, createWebHashHistory } from 'vue-router'
import NewsView from './views/NewsView.vue'
import DetailView from './views/DetailView.vue'
import SourcesView from './views/SourcesView.vue'
import UpdatesView from './views/UpdatesView.vue'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'news', component: NewsView },
    { path: '/item/:id', name: 'item', component: DetailView },
    { path: '/updates', name: 'updates', component: UpdatesView },
    { path: '/sources', name: 'sources', component: SourcesView }
  ],
  scrollBehavior(to, from, saved) {
    return saved || { top: 0 }
  }
})
