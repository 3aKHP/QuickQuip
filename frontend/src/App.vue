<template>
  <div class="layout">
    <nav>
      <span class="brand">QuickQuip</span>
      <button :class="{ active: view === 'stats' }" @click="view = 'stats'">统计</button>
      <button :class="{ active: view === 'rules' }" @click="view = 'rules'">规则</button>
      <button :class="{ active: view === 'groups' }" @click="view = 'groups'">群组</button>
    </nav>
    <main>
      <StatsView v-if="view === 'stats'" />
      <RulesView v-else-if="view === 'rules'" />
      <GroupsView v-else-if="view === 'groups'" />
    </main>
  </div>
</template>

<script>
import StatsView from './views/StatsView.vue'
import RulesView from './views/RulesView.vue'
import GroupsView from './views/GroupsView.vue'

export default {
  components: { StatsView, RulesView, GroupsView },
  data: () => ({ view: 'stats' }),
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
.card h3 { margin-bottom: 8px; font-size: 15px; }
.card p { color: #8b949e; margin-bottom: 6px; }
details { margin-top: 8px; }
summary { cursor: pointer; color: #58a6ff; font-size: 13px; }
ol { padding-left: 20px; margin-top: 6px; color: #8b949e; font-size: 13px; line-height: 1.8; }

.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.toolbar label { display: flex; align-items: center; gap: 6px; color: #8b949e; }
.toolbar select, .toolbar input {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 5px 8px;
  font-size: 14px;
}

.rule-grid { display: flex; flex-direction: column; gap: 4px; }
.rule-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 10px;
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 4px;
}
.rule-name { flex: 1; font-family: monospace; font-size: 13px; }

button { cursor: pointer; border-radius: 4px; border: none; padding: 5px 12px; font-size: 13px; }
.btn-on  { background: #238636; color: #fff; }
.btn-off { background: #6e7681; color: #fff; }
.btn-on:hover  { background: #2ea043; }
.btn-off:hover { background: #8b949e; }
.small { padding: 2px 8px; font-size: 12px; }

.groups-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
section {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 16px;
}
section h3 { margin-bottom: 12px; }
ul { list-style: none; display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
li { display: flex; align-items: center; justify-content: space-between; font-family: monospace; }
.add-row { display: flex; gap: 8px; }
.add-row input {
  flex: 1;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 5px 8px;
  font-size: 14px;
}
.add-row button { background: #238636; color: #fff; }

.error { color: #f85149; }
.muted { color: #6e7681; font-size: 13px; }
h2 { margin-bottom: 16px; font-size: 16px; }
</style>
