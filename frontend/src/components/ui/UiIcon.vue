<template>
  <component :is="resolved" :size="size" :stroke-width="strokeWidth" />
</template>

<script setup lang="ts">
import {
  BarChart3, ToggleLeft, Users, Brain, FileText, MessageCircle,
  Drama, BookUser, SlidersHorizontal, Zap, BookOpen, Newspaper,
  Settings, Stethoscope, Server, Clock, ShieldCheck, Coins, Swords,
  Loader2, CircleX, Info, LogOut, Menu, Bot, Sun, Moon, ChevronRight,
  Search, Plus, Trash2, Pencil, RotateCw, Upload, ExternalLink,
  Check, X, ChevronDown, FolderOpen, Lock, RefreshCw, LayoutDashboard,
  MessagesSquare, BrainCircuit, ServerCog, Gamepad2, Gauge, Network,
  Cloud, ArrowRight, ChevronUp, Send, FileCode, ListChecks,
  AlertTriangle, Play, Save, ChevronLeft, Download
} from 'lucide-vue-next'
import { computed } from 'vue'
import type { Component } from 'vue'

type IconName =
  | 'BarChart3' | 'ToggleLeft' | 'Users' | 'Brain' | 'FileText'
  | 'MessageCircle' | 'Drama' | 'BookUser' | 'SlidersHorizontal'
  | 'Zap' | 'BookOpen' | 'Newspaper' | 'Settings' | 'Stethoscope'
  | 'Server' | 'Clock' | 'ShieldCheck' | 'Coins' | 'Swords'
  | 'Loader2' | 'CircleX' | 'Info' | 'LogOut' | 'Menu' | 'Bot'
  | 'Sun' | 'Moon' | 'ChevronRight' | 'Search' | 'Plus' | 'Trash2'
  | 'Pencil' | 'RotateCw' | 'Upload' | 'ExternalLink' | 'Check'
  | 'X' | 'ChevronDown' | 'FolderOpen' | 'Lock' | 'RefreshCw'
  | 'LayoutDashboard' | 'MessagesSquare' | 'BrainCircuit' | 'ServerCog'
  | 'Gamepad2' | 'Gauge' | 'Network' | 'Cloud' | 'ArrowRight'
  | 'ChevronUp' | 'Send' | 'FileCode' | 'ListChecks' | 'AlertTriangle'
  | 'Play' | 'Save' | 'ChevronLeft' | 'Download'

const ICON_MAP: Record<IconName, Component> = {
  BarChart3, ToggleLeft, Users, Brain, FileText,
  MessageCircle, Drama, BookUser, SlidersHorizontal,
  Zap, BookOpen, Newspaper, Settings, Stethoscope,
  Server, Clock, ShieldCheck, Coins, Swords,
  Loader2, CircleX, Info, LogOut, Menu, Bot,
  Sun, Moon, ChevronRight, Search, Plus, Trash2,
  Pencil, RotateCw, Upload, ExternalLink, Check,
  X, ChevronDown, FolderOpen, Lock, RefreshCw, LayoutDashboard,
  MessagesSquare, BrainCircuit, ServerCog, Gamepad2, Gauge, Network,
  Cloud, ArrowRight, ChevronUp, Send, FileCode, ListChecks,
  AlertTriangle, Play, Save, ChevronLeft, Download
}

const props = defineProps<{
  name: IconName | string
  size?: number
  strokeWidth?: number
}>()

const resolved = computed(() => {
  const c = ICON_MAP[props.name as IconName]
  return c || Info
})
</script>
