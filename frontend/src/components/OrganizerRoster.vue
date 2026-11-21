<template>
  <div v-if="state" class="organizer-roster" data-roster :data-mode="state.mode" :data-complete="complete" :aria-busy="busy">
    <div class="roster-toolbar">
      <div class="tabs" role="tablist" aria-label="名单分类" @keydown="onKey">
        <button v-for="type in types" :id="uid + '-tab-' + type.key" :key="type.key" type="button" role="tab" :class="{ active: state.tab === type.key }" :aria-selected="state.tab === type.key" :tabindex="state.tab === type.key ? 0 : -1" :aria-controls="uid + '-panel-' + type.key" @click="$emit('tab', type.key)">{{ type.label }}（{{ totalFor(type.key) }}{{ complete ? '' : '+' }}）</button>
      </div>
      <button type="button" class="ghost" :disabled="anyBusy || refreshing" @click="$emit('refresh')">刷新名单</button>
    </div>
    <p v-if="busy" class="hint" role="status">{{ native ? '正在读取本类名单…' : '正在读取完整名单（已读 ' + state.items.length + ' 条）…' }}</p>
    <div v-if="error" class="load-error" role="alert"><p>{{ error }}；{{ native ? '当前页已保留，可重试原失败页。' : '已读名单保留，未读部分不代表无人报名。' }}</p><button type="button" class="ghost" :disabled="busy" @click="$emit('retry')">{{ native ? '重试本类名单' : '继续读取名单' }}</button></div>
    <div :id="uid + '-panel-' + state.tab" role="tabpanel" :aria-labelledby="uid + '-tab-' + state.tab" tabindex="0">
      <table v-if="pageItems.length" class="roster-table">
        <caption class="sr-only">{{ types.find(type => type.key === state.tab)?.label }}</caption>
        <thead>
          <tr>
            <th scope="col">昵称</th>
            <th scope="col" class="roster-status">{{ state.tab === 'WAITING' ? '队列排名' : '参与状态' }}</th>
            <th v-if="state.tab === 'INVITED'" scope="col" class="roster-expiry">确认截止</th>
            <th scope="col" class="roster-action">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in pageItems" :key="r.id" class="roster-member" :data-member-id="r.id">
            <th scope="row">{{ r.nickname }}</th>
            <td class="roster-status" :data-label="state.tab === 'WAITING' ? '队列排名' : '参与状态'">{{ state.tab === 'FORMAL' ? '正式成员' : state.tab === 'INVITED' ? '待确认' : '第 ' + ((page - 1) * size + i + 1) + ' 名' }}</td>
            <td v-if="state.tab === 'INVITED'" class="roster-expiry" data-label="确认截止"><time v-if="expires(r)" :datetime="expires(r)">{{ displayTime(expires(r)) }}</time><span v-else>期限暂无数据，请刷新</span></td>
            <td class="roster-action" data-label="操作">
              <button v-if="String(r.user_id) !== String(userId)" type="button" class="warn" :disabled="locked || busy" :title="'将 ' + r.nickname + ' 移出本活动'" @click="$emit('remove', r)">移出成员</button>
              <span v-else class="hint">本人</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length && complete" class="meta">{{ state.tab === 'FORMAL' ? '暂无正式成员。' : state.tab === 'INVITED' ? '暂无待确认。' : '暂无候补。' }}</p>
      <p v-else-if="!rows.length" class="meta">本类名单尚未读取完整，请等待或继续读取；不能据此判断为空。</p>
      <div v-if="rows.length" class="inline-actions" aria-label="本类名单分页">
        <button type="button" class="ghost" :disabled="busy || page <= 1" @click="$emit('page', state.tab, page - 1)">上一页</button>
        <span role="status">第 {{ page }} / {{ Math.max(1, Math.ceil(totalFor(state.tab) / size)) }} 页{{ complete ? '' : '（已读部分）' }}</span>
        <button type="button" class="ghost" :disabled="busy || page * size >= totalFor(state.tab)" @click="$emit('page', state.tab, page + 1)">下一页</button>
      </div>
    </div>
    <p class="hint">名单只显示昵称与参与状态，不含联系方式，仅组织者可见。</p>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance } from 'vue'
const props = defineProps({ state: Object, userId: [String, Number], invitations: Array, locked: Boolean, refreshing: Boolean })
const emit = defineEmits(['tab', 'page', 'retry', 'refresh', 'remove'])
const uid = 'roster-' + getCurrentInstance().uid
const native = computed(() => props.state.mode === 'sections')
const section = computed(() => props.state.sections?.[props.state.tab])
const size = computed(() => native.value ? section.value.pageSize : 20)
const complete = computed(() => native.value || props.state.complete)
const busy = computed(() => !!(native.value ? section.value.busy : props.state.busy))
const anyBusy = computed(() => native.value ? Object.values(props.state.sections).some(s => s.busy) : props.state.busy)
const error = computed(() => native.value ? section.value.error : props.state.error)
const types = [{ key: 'FORMAL', label: '正式名单' }, { key: 'INVITED', label: '待确认' }, { key: 'WAITING', label: '候补队列' }]
const rowsFor = key => native.value ? props.state.sections[key].items : props.state.items.filter(r => r.status === key)
const totalFor = key => native.value ? props.state.sections[key].total : rowsFor(key).length
const rows = computed(() => rowsFor(props.state.tab))
const page = computed(() => native.value ? section.value.page : Math.min(props.state.pages[props.state.tab], Math.max(1, Math.ceil(rows.value.length / size.value))))
const pageItems = computed(() => native.value ? rows.value : rows.value.slice((page.value - 1) * size.value, page.value * size.value))
function expires(r) {
  return r.invitation_expires_at || (props.invitations || []).find(i => String(i.participation_id) === String(r.id))?.expires_at
}
function displayTime(s) { return String(s).replace('T', ' ').replace(/(\d{2}:\d{2}):\d{2}.*$/, '$1') }
function onKey(e) {
  if (e.target.getAttribute('role') !== 'tab') return
  const buttons = [...e.currentTarget.querySelectorAll('[role="tab"]')]
  let index = buttons.indexOf(e.target)
  if (e.key === 'ArrowRight') index = (index + 1) % buttons.length
  else if (e.key === 'ArrowLeft') index = (index - 1 + buttons.length) % buttons.length
  else if (e.key === 'Home') index = 0
  else if (e.key === 'End') index = buttons.length - 1
  else return
  e.preventDefault()
  buttons[index].focus()
}
</script>
