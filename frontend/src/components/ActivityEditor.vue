<template>
  <form class="reschedule-box activity-editor" novalidate @submit.prevent="submit" :aria-busy="busy">
    <h4>{{ timeOnly ? '修改时间' : '编辑活动' }}（仅报名截止前）</h4>
    <p class="hint">保留原活动和报名记录；保存会通知受影响成员。{{ timeOnly ? '仅提交三个时间字段。' : '可修改名称、类别、介绍、参与条件、地点、容量和三个时间。' }}</p>
    <fieldset :disabled="busy || !editable">
      <template v-for="field in visibleFields" :key="field.key">
        <label class="field-label" :for="prefix + field.key">{{ field.label }}{{ field.required ? '（必填）' : '（可选）' }}</label>
        <select v-if="field.key === 'category'" :id="prefix + field.key" v-model="draft[field.key]" :aria-invalid="!!errors[field.key]" :aria-describedby="prefix + field.key + '-hint'" @change="errors[field.key] = ''">
          <option value="">请选择类别</option><option>羽毛球</option><option>桌游</option><option>学习组</option><option>其他</option>
        </select>
        <textarea v-else-if="['description', 'conditions'].includes(field.key)" :id="prefix + field.key" v-model="draft[field.key]" rows="3" :aria-invalid="!!errors[field.key]" :aria-describedby="prefix + field.key + '-hint'" @input="errors[field.key] = ''"></textarea>
        <input v-else :id="prefix + field.key" v-model="draft[field.key]" :type="field.key === 'capacity' ? 'number' : 'text'" :min="field.key === 'capacity' ? 1 : undefined" :max="field.key === 'capacity' ? 100 : undefined" :step="field.key === 'capacity' ? 1 : undefined" :aria-invalid="!!errors[field.key]" :aria-describedby="prefix + field.key + '-hint'" @input="errors[field.key] = ''" />
        <p :id="prefix + field.key + '-hint'" class="field-hint" :class="{ 'warn-hint': errors[field.key] }" :role="errors[field.key] ? 'alert' : undefined">{{ errors[field.key] || field.hint }}</p>
      </template>
    </fieldset>
    <p v-if="!editable" class="field-hint warn-hint" role="status">当前已不在可编辑阶段，不能保存。</p>
    <div v-if="conflict" class="edit-conflict" role="status">
      <h4>活动已被修改，请核对后再保存</h4>
      <p class="hint">你的输入已保留，不会自动覆盖服务器。核对后会采用最新版本；你没改过的字段跟随服务器更新。</p>
      <div v-for="row in differences" :key="row.key" class="edit-difference">
        <b>{{ row.label }}</b><p>打开时：{{ row.before || '（空）' }}</p><p>服务器：{{ row.latest || '（空）' }}</p><p>你的输入：{{ row.draft || '（空）' }}</p>
      </div>
      <p v-if="conflict.latest && !differences.length" class="hint">字段内容相同，但版本已更新，仍需核对后使用新版本。</p>
      <button type="button" class="ghost" :disabled="busy" @click="fetchLatest">重新读取最新版本</button>
      <button v-if="conflict.latest" type="button" class="primary" :disabled="busy" @click="reviewLatest">已核对，保留我的修改并采用新版本</button>
    </div>
    <p v-if="error" class="field-hint warn-hint" role="alert">{{ error }}</p>
    <button type="submit" class="primary" :disabled="busy || !editable || !!conflict || !version">{{ busy ? '提交中…' : '确认修改' }}</button>
    <button type="button" class="ghost" @click="$emit('close')">取消</button>
    <button v-if="!version && !conflict" type="button" class="ghost" :disabled="busy" @click="fetchLatest">重新读取版本</button>
  </form>
</template>

<script setup>
import { computed, nextTick, onUnmounted, ref } from 'vue'

const props = defineProps({ activity: Object, editable: Boolean, timeOnly: Boolean, session: String, request: Function, save: Function, clock: Function })
const emit = defineEmits(['saved', 'close'])
const fields = [
  { key: 'title', label: '名称', required: true, limit: 50, hint: '1–50 字（Unicode 码点）。' },
  { key: 'category', label: '类别', required: true, hint: '仅支持既有四种类别。' },
  { key: 'description', label: '介绍', limit: 2000, hint: '最多 2000 字（Unicode 码点）。' },
  { key: 'conditions', label: '参与条件', limit: 500, hint: '最多 500 字（Unicode 码点）；留空表示无附加条件。' },
  { key: 'location', label: '地点', required: true, limit: 100, hint: '1–100 字（Unicode 码点）。' },
  { key: 'capacity', label: '人数上限', required: true, hint: '1–100 的整数，不得低于正式人数与有效预留之和；以服务器核算为准。' },
  { key: 'deadline', label: '报名截止', required: true, hint: '年-月-日 时:分（可带秒）；保留未改时间精度，现在 < 截止 ≤ 开始 < 结束。' },
  { key: 'start_time', label: '开始时间', required: true, hint: '年-月-日 时:分，例如 2026-12-01 10:00。' },
  { key: 'end_time', label: '结束时间', required: true, hint: '年-月-日 时:分；须晚于开始。' },
]
const timeKeys = ['deadline', 'start_time', 'end_time']
const visibleFields = computed(() => fields.filter(f => !props.timeOnly || timeKeys.includes(f.key)))
const aid = props.activity.activity_id || props.activity.id
const session = props.session
const prefix = (props.timeOnly ? 'time-edit-' : 'activity-edit-')
let active = true
let readSeq = 0
onUnmounted(() => { active = false; readSeq++ })
const current = () => active && props.session === session && String(props.activity.activity_id || props.activity.id) === String(aid)

function values(a) {
  return Object.fromEntries(fields.map(f => [f.key, timeKeys.includes(f.key)
    ? displayTimestamp(a[f.key]) : (a[f.key] ?? '')]))
}
// 时间精度属于原数据：只改名称不能顺带把原有的秒/纳秒归零。
function displayTimestamp(value) {
  const m = String(value || '').match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2}))?(\.\d{1,9})?(Z|[+-]\d{2}:?\d{2})?$/)
  if (!m) return String(value || '')
  let wall = m[1] + 'T' + m[2] + ':' + (m[3] || '00')
  if (m[5]) {
    const instant = Date.parse(wall + m[5])
    if (!Number.isFinite(instant)) return String(value || '')
    wall = new Date(instant + 8 * 3600000).toISOString().slice(0, 19)
  }
  return (wall + (m[4] || '')).replace('T', ' ').replace(/:00$/, '')
}
// 新契约有activity_version时原样回传。旧详情的updated_at按现行Java
// LocalDateTime.toString口径归一，保留纳秒，不把版本当普通分钟时间截断。
function versionOf(a) {
  if (a.activity_version) return String(a.activity_version)
  const m = String(a.updated_at || '').match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?$/)
  if (!m) return ''
  let wall = m[1] + 'T' + m[2] + ':' + (m[3] || '00')
  if (m[5]) {
    const instant = Date.parse(wall + m[5])
    if (!Number.isFinite(instant)) return ''
    wall = new Date(instant + 8 * 3600000).toISOString().slice(0, 19)
  }
  const fraction = (m[4] || '').replace(/0+$/, '')
  const nanos = fraction ? '.' + fraction.padEnd(Math.ceil(fraction.length / 3) * 3, '0') : ''
  return wall.slice(0, 16) + (wall.slice(17) !== '00' || nanos ? wall.slice(16) + nanos : '')
}
const baseline = ref(values(props.activity))
const draft = ref({ ...baseline.value })
const version = ref(versionOf(props.activity))
const busy = ref(false), errors = ref({}), conflict = ref(null)
const error = ref(version.value ? '' : '缺少可核验的活动版本，请重新读取后再保存。')
const differences = computed(() => {
  if (!conflict.value?.latest) return []
  const latest = values(conflict.value.latest)
  return visibleFields.value.filter(f => String(latest[f.key]) !== String(baseline.value[f.key])
    || String(draft.value[f.key]) !== String(baseline.value[f.key]))
    .map(f => ({ key: f.key, label: f.label, before: baseline.value[f.key], latest: latest[f.key], draft: draft.value[f.key] }))
})

function apiTime(raw) {
  const m = String(raw).trim().match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::(\d{2})(\.\d{1,9})?)?$/)
  if (!m) return null
  const wall = m[1] + 'T' + m[2] + ':' + (m[3] || '00')
  const t = Date.parse(wall + '+08:00')
  if (!Number.isFinite(t) || new Date(t + 8 * 3600000).toISOString().slice(0, 19) !== wall) return null
  return wall + (m[4] || '')
}
function validate() {
  const result = {}, payload = {}
  for (const f of visibleFields.value) {
    const raw = String(draft.value[f.key])
    if (f.required && !raw.trim()) result[f.key] = f.label + '不能为空'
    if (f.limit && [...raw].length > f.limit) result[f.key] = f.label + '不能超过 ' + f.limit + ' 字'
    payload[f.key] = raw
  }
  if (!props.timeOnly) {
    if (!['羽毛球', '桌游', '学习组', '其他'].includes(draft.value.category)) result.category = '请选择既有类别'
    if (!/^\d+$/.test(String(draft.value.capacity)) || Number(draft.value.capacity) < 1 || Number(draft.value.capacity) > 100) result.capacity = '人数上限需为1–100的整数'
    payload.capacity = Number(draft.value.capacity)
  }
  for (const k of timeKeys) {
    payload[k] = apiTime(draft.value[k])
    if (!payload[k]) result[k] = '请填写有效的年-月-日 时:分'
  }
  if (timeKeys.every(k => payload[k])) {
    const times = timeKeys.map(k => Date.parse(payload[k] + '+08:00'))
    if (times[0] <= props.clock()) result.deadline = '报名截止必须晚于现在'
    if (times[0] > times[1]) result.start_time = '报名截止不得晚于开始时间'
    if (times[1] >= times[2]) result.end_time = '结束时间须晚于开始时间'
  }
  errors.value = result
  return Object.keys(result).length ? null : payload
}
async function fetchLatest() {
  const seq = ++readSeq
  busy.value = true
  try {
    const latest = await props.request('/activities/' + aid)
    if (!current() || seq !== readSeq) return
    conflict.value = { latest }
    error.value = versionOf(latest) ? '' : '服务器未返回可核验的版本，不能保存。'
  } catch (e) {
    if (current() && seq === readSeq) error.value = '最新版本读取失败，输入已保留：' + e.message
  } finally { if (current() && seq === readSeq) busy.value = false }
}
function reviewLatest() {
  const latest = conflict.value?.latest, nextVersion = latest && versionOf(latest)
  if (!nextVersion) return
  const next = values(latest)
  draft.value = Object.fromEntries(fields.map(f => [f.key, String(draft.value[f.key]) === String(baseline.value[f.key]) ? next[f.key] : draft.value[f.key]]))
  baseline.value = next
  version.value = nextVersion
  conflict.value = null
  error.value = '已核对新版本并保留你的修改，请再次保存才会提交。'
}
async function submit() {
  if (!current() || busy.value || conflict.value || !props.editable || !version.value) return
  const payload = validate()
  if (!payload) { await focusError(); return }
  busy.value = true; error.value = ''
  try {
    const result = await props.save(aid, { ...payload, expectedVersion: version.value })
    if (current()) emit('saved', { ...result, activity_id: aid })
  } catch (e) {
    if (!current()) return
    if (e.status === 409 || e.code === 'CONFLICT') {
      conflict.value = { latest: null }
      await fetchLatest()
    } else {
      errors.value = e.data?.fieldErrors || {}
      error.value = (!e.status || e.status >= 500 ? '提交结果暂不确定，请先核对最新版本；' : '未保存，输入已保留：') + e.message
      if (!e.status || e.status >= 500) { conflict.value = { latest: null }; await fetchLatest() }
      await focusError()
    }
  } finally { if (current()) busy.value = false }
}
async function focusError() {
  await nextTick()
  const key = visibleFields.value.find(f => errors.value[f.key])?.key
  if (key) document.getElementById(prefix + key)?.focus()
}
</script>
