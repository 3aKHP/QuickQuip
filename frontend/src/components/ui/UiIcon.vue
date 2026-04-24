<template>
  <component :is="iconComp" v-if="iconComp" :size="size" :stroke-width="strokeWidth" />
</template>

<script setup>
import { computed } from 'vue'
import {
  AlertTriangle, ArrowLeft, BarChart2, BarChart3, BookOpen, Bot, Brain,
  CalendarCheck, Check, CircleX, Drama, FileText, Inbox, Info, Loader2,
  Lock, LogOut, MessageCircle, Search, ArrowUp, ArrowDown, MousePointerClick,
  Newspaper, Pencil, Play, Plus, RefreshCw, RotateCcw, Save, Settings,
  SlidersHorizontal, ToggleLeft, Trash2, Users, X, Zap,
  Send, Stethoscope, FileCode,
} from 'lucide-vue-next'

const ICON_MAP = {
  AlertTriangle, ArrowLeft, BarChart2, BarChart3, BookOpen, Bot, Brain,
  CalendarCheck, Check, CircleX, Drama, FileText, Inbox, Info, Loader2,
  Lock, LogOut, MessageCircle, Search, ArrowUp, ArrowDown, MousePointerClick,
  Newspaper, Pencil, Play, Plus, RefreshCw, RotateCcw, Save, Settings,
  SlidersHorizontal, ToggleLeft, Trash2, Users, X, Zap,
  Send, Stethoscope, FileCode,
}

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [String, Number], default: 16 },
  strokeWidth: { type: [String, Number], default: 2 },
})

const iconComp = computed(() => ICON_MAP[props.name] || null)
</script>
