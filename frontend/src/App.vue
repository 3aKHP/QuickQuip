<template>
  <div class="layout">
    <nav>
      <span class="brand">QuickQuip</span>
      <button :class="{ active: view === 'stats' }" @click="view = 'stats'">统计</button>
      <button :class="{ active: view === 'rules' }" @click="view = 'rules'">规则</button>
      <button :class="{ active: view === 'groups' }" @click="view = 'groups'">群组</button>
      <button :class="{ active: view === 'config' }" @click="view = 'config'">配置</button>
    </nav>
    <main>
      <StatsView v-if="view === 'stats'" />
      <RulesView v-else-if="view === 'rules'" />
      <GroupsView v-else-if="view === 'groups'" />
      <ConfigView v-else-if="view === 'config'" />
    </main>
    <transition name="toast">
      <div v-if="toastMsg" class="toast" :class="toastType">{{ toastMsg }}</div>
    </transition>
  </div>
</template>

<script>
import StatsView from './views/StatsView.vue'
import RulesView from './views/RulesView.vue'
import GroupsView from './views/GroupsView.vue'
import ConfigView from './views/ConfigView.vue'
import { toastMsg, toastType } from './toast.js'

export default {
  components: { StatsView, RulesView, GroupsView, ConfigView },
  data: () => ({ view: 'stats', toastMsg, toastType }),
}
</script>

<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: system-ui, sans-serif;
  font-size: 14px;
  background: #0d1117;
  color: #c9d1d9;
  min-height: 100vh;
}

.layout { display: flex; flex-direction: column; min-height: 100vh; }

nav {
  background: #161b22;
  border-bottom: 1px solid #30363d;
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 4px;
  height: 44px;
}
.brand { font-weight: 600; margin-right: 12px; color: #58a6ff; }
nav button {
  background: none;
  border: none;
  color: #8b949e;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}
nav button:hover { color: #c9d1d9; background: #21262d; }
nav button.active { color: #c9d1d9; background: #21262d; }

main { padding: 24px; flex: 1; }

.card {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 12px;
}

h2 { font-size: 18px; margin-bottom: 16px; color: #e6edf3; }
h3 { font-size: 15px; margin-bottom: 10px; color: #e6edf3; }

.error { color: #f85149; }
.muted { color: #8b949e; font-size: 13px; }

details summary { cursor: pointer; color: #8b949e; font-size: 13px; margin-top: 8px; }
details ol { margin: 6px 0 0 20px; font-size: 13px; color: #8b949e; }

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.toolbar label { display: flex; align-items: center; gap: 6px; color: #8b949e; }
.toolbar select, .toolbar input {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 4px 8px;
  font-size: 14px;
}

button {
  background: #21262d;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 5px 12px;
  cursor: pointer;
  font-size: 13px;
}
button:hover { background: #30363d; }
button:disabled { opacity: 0.5; cursor: default; }

.btn-on  { background: #1f6feb33; border-color: #1f6feb; color: #58a6ff; }
.btn-off { background: #f8514933; border-color: #f85149; color: #f85149; }
.btn-on:hover  { background: #1f6feb55; }
.btn-off:hover { background: #f8514955; }
.small { padding: 2px 8px; font-size: 12px; }

.rule-grid { display: flex; flex-direction: column; gap: 4px; }
.rule-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 4px;
}
.rule-name { font-size: 13px; font-family: monospace; color: #c9d1d9; }

/* Toggle switch */
.toggle-wrap { display: flex; align-items: center; gap: 8px; }
.toggle {
  position: relative;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
}
.toggle input { opacity: 0; width: 0; height: 0; }
.toggle-slider {
  position: absolute;
  inset: 0;
  background: #30363d;
  border-radius: 20px;
  cursor: pointer;
  transition: background 0.2s;
}
.toggle-slider::before {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  left: 3px;
  top: 3px;
  background: #8b949e;
  border-radius: 50%;
  transition: transform 0.2s, background 0.2s;
}
.toggle input:checked + .toggle-slider { background: #1f6feb44; }
.toggle input:checked + .toggle-slider::before { transform: translateX(16px); background: #58a6ff; }

.groups-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 600px) { .groups-layout { grid-template-columns: 1fr; } }

.groups-layout section {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 16px;
}
.groups-layout ul { list-style: none; margin-bottom: 12px; }
.groups-layout li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid #21262d;
  font-size: 13px;
}
.groups-layout li:last-child { border-bottom: none; }
.add-row { display: flex; gap: 8px; margin-top: 8px; }
.add-row input, .add-row select {
  flex: 1;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 4px 8px;
  font-size: 13px;
}

/* Toast */
.toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: #21262d;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 8px 20px;
  font-size: 13px;
  color: #c9d1d9;
  z-index: 9999;
  pointer-events: none;
  white-space: nowrap;
}
.toast.error { border-color: #f85149; color: #f85149; }
.toast.info  { border-color: #58a6ff; color: #58a6ff; }
.toast-enter-active, .toast-leave-active { transition: opacity 0.2s, transform 0.2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(8px); }
</style>
