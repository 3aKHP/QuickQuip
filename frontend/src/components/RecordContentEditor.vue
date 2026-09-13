<template>
  <div class="record-editor">
    <div v-for="(part, i) in modelValue.parts" :key="i" class="part">
      <textarea v-if="part.type === 'text'" :value="part.text" rows="2" aria-label="正文" @input="changeText(i, ($event.target as HTMLTextAreaElement).value)" />
      <span v-else-if="part.type === 'member'" class="member">{{ part.usage === 'identity' ? '' : '@' }}{{ part.display || part.name || `QQ${part.qq}` }} ({{ part.qq }})</span>
      <span v-else>{{ part.type === 'all' ? '@全体成员' : `[${part.media}]` }}</span>
      <UiButton size="sm" variant="ghost" @click="remove(i)">删除</UiButton>
      <UiButton v-if="part.type === 'member'" size="sm" @click="replaceIndex = i">更换成员</UiButton>
    </div>
    <div class="controls">
      <UiButton size="sm" @click="appendText">添加文字</UiButton>
      <input v-model="query" placeholder="按名字、别名或 QQ 查找成员" @keyup.enter="search()" />
      <UiButton size="sm" @click="search()" :loading="loading">查找成员</UiButton>
      <span v-if="replaceIndex !== null">正在更换第 {{ replaceIndex + 1 }} 段 <button type="button" @click="replaceIndex = null">取消</button></span>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="controls"><UiButton v-for="member in candidates" :key="member.qq" size="sm" @click="select(member)">{{ member.name }} ({{ member.qq }})</UiButton></div>
    <UiButton v-if="hasMore" size="sm" :loading="loading" @click="search(true)">继续加载成员</UiButton>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { fetchMemberCandidates, type RecordBody, type RecordPart, type MemberCandidate } from '../api/recordContent'
import UiButton from './ui/UiButton.vue'
const props = defineProps<{ modelValue: RecordBody; groupId: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: RecordBody] }>()
const loading = ref(false); const hasMore = ref(false); let searchGeneration = 0
const query = ref(''); const candidates = ref<MemberCandidate[]>([]); const error = ref(''); const replaceIndex = ref<number | null>(null)
function update(parts: RecordPart[]) { emit('update:modelValue', { version: 1, parts }) }
function changeText(i: number, text: string) { update(props.modelValue.parts.map((p, j) => i === j && p.type === 'text' ? { ...p, text } : p)) }
function remove(i: number) { update(props.modelValue.parts.filter((_, j) => i !== j)); replaceIndex.value = null }
function appendText() { update([...props.modelValue.parts, { type: 'text', text: '' }]) }
async function search(more = false) {
  if (more && loading.value) return
  const generation = ++searchGeneration
  const offset = more ? candidates.value.length : 0
  error.value = ''; loading.value = true
  try {
    const result = await fetchMemberCandidates(props.groupId, query.value, offset)
    if (generation !== searchGeneration) return
    candidates.value = more ? [...candidates.value, ...result] : result
    hasMore.value = result.length === 100
    if (!candidates.value.length) error.value = '未找到成员'
  } catch (e) { if (generation === searchGeneration) error.value = (e as Error).message }
  finally { if (generation === searchGeneration) loading.value = false }
}

function select(member: MemberCandidate) {
  const part: RecordPart = { type: 'member', ...member, usage: 'mention' }
  const parts = [...props.modelValue.parts]
  if (replaceIndex.value !== null) {
    const previous = parts[replaceIndex.value]
    parts[replaceIndex.value] = { ...part, usage: previous?.type === 'member' ? previous.usage : 'mention' }
  } else parts.push(part, { type: 'text', text: '' })
  update(parts); replaceIndex.value = null; candidates.value = []; hasMore.value = false; searchGeneration++; loading.value = false
}

watch([() => props.groupId, query], () => { candidates.value = []; hasMore.value = false; searchGeneration++; loading.value = false })
watch(() => props.groupId, () => { replaceIndex.value = null })
</script>

<style scoped>
.record-editor { display: flex; flex-direction: column; gap: var(--qq-gap-sm); }
.part, .controls { display: flex; align-items: center; flex-wrap: wrap; gap: var(--qq-gap-xs); }
.part textarea { flex: 1; min-width: 200px; }
.member { padding: 6px 10px; border-radius: var(--qq-radius-card); background: var(--qq-surface); }
</style>
