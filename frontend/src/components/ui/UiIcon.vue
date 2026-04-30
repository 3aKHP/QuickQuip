<template>
  <component :is="iconComp" v-if="iconComp" :size="size" :stroke-width="strokeWidth" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  AlertTriangle, ArrowLeft, BarChart2, BarChart3, BookOpen, BookUser, Bot, Brain,
  CalendarCheck, Check, CircleX, Drama, FileText, Inbox, Info, Loader2,
  Lock, LogOut, MessageCircle, Search, ArrowUp, ArrowDown, MousePointerClick,
  Newspaper, Pencil, Play, Plus, RefreshCw, RotateCcw, Save, Settings,
  SlidersHorizontal, ToggleLeft, Trash2, Users, X, Zap,
  Send, Stethoscope, FileCode, Download,
} from 'lucide-vue-next'

const ICON_MAP = {
  AlertTriangle, ArrowLeft, BarChart2, BarChart3, BookOpen, BookUser, Bot, Brain,
  CalendarCheck, Check, CircleX, Drama, FileText, Inbox, Info, Loader2,
  Lock, LogOut, MessageCircle, Search, ArrowUp, ArrowDown, MousePointerClick,
  Newspaper, Pencil, Play, Plus, RefreshCw, RotateCcw, Save, Settings,
  SlidersHorizontal, ToggleLeft, Trash2, Users, X, Zap,
  Send, Stethoscope, FileCode, Download,
}

export type IconName = keyof typeof ICON_MAP

const props = defineProps<{
  name: IconName | string
  size?: number
  strokeWidth?: number
}>()

const iconComp = computed(() => (ICON_MAP as Record<string, any>)[props.name] || null)
</script>
