<template>
  <component :is="iconComp" v-if="iconComp" :size="size" :stroke-width="strokeWidth" />
</template>

<script>
import { computed } from 'vue'
import {
  AlertTriangle,
  ArrowLeft,
  BarChart2,
  BarChart3,
  BookOpen,
  Bot,
  Brain,
  CalendarCheck,
  Check,
  CircleX,
  Drama,
  FileText,
  Inbox,
  Info,
  Loader2,
  Lock,
  LogOut,
  MessageCircle,
  Search,
  ArrowUp,
  ArrowDown,
  MousePointerClick,
  Newspaper,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Settings,
  SlidersHorizontal,
  ToggleLeft,
  Trash2,
  Users,
  X,
  Zap,
} from 'lucide-vue-next'

const ICON_MAP = {
  AlertTriangle,
  ArrowLeft,
  BarChart2,
  BarChart3,
  BookOpen,
  Bot,
  Brain,
  CalendarCheck,
  Check,
  CircleX,
  Drama,
  FileText,
  Inbox,
  Info,
  Loader2,
  Lock,
  LogOut,
  MessageCircle,
  Search,
  ArrowUp,
  ArrowDown,
  MousePointerClick,
  Newspaper,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Settings,
  SlidersHorizontal,
  ToggleLeft,
  Trash2,
  Users,
  X,
  Zap,
}

export default {
  name: 'UiIcon',
  props: {
    name: { type: String, required: true },
    size: { type: [String, Number], default: 16 },
    strokeWidth: { type: [String, Number], default: 2 },
  },
  setup(props) {
    const iconComp = computed(() => ICON_MAP[props.name] || null)
    return { iconComp }
  },
}
</script>
