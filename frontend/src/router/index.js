import { createRouter, createWebHashHistory } from 'vue-router'
import { NAV_ITEMS } from '../config/nav.js'

const routes = [
  { path: '/', redirect: `/${NAV_ITEMS[0].key}` },
  ...NAV_ITEMS.map(item => ({
    path: `/${item.key}`,
    name: item.key,
    component: item.component,
  })),
  { path: '/:pathMatch(.*)*', redirect: `/${NAV_ITEMS[0].key}` },
]

export const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes,
})
