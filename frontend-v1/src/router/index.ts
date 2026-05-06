import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { NAV_ITEMS } from '../config/nav'
import type { NavItem } from '../config/nav'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: `/${NAV_ITEMS[0].key}` },
  ...NAV_ITEMS.map((item: NavItem) => ({
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
