import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { NAV_ITEMS } from '../config/nav'
import type { NavItem } from '../config/nav'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'home', component: NAV_ITEMS[0].component },
  { path: '/logs', redirect: '/logs-live' },
  ...NAV_ITEMS.slice(1).map((item: NavItem) => ({
    path: `/${item.key}`,
    name: item.key,
    component: item.component,
  })),
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes,
})
