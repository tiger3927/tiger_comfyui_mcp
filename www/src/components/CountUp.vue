<script setup>
// 数字滚动组件：value 变化时从旧值平滑滚动到新值（easeOutCubic），默认千分位。
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  value: { type: Number, default: 0 },
  duration: { type: Number, default: 650 },
  format: { type: Boolean, default: true },
  decimals: { type: Number, default: 0 },
})

const display = ref(0)
let raf = null

function animateTo(target) {
  cancelAnimationFrame(raf)
  const t = Number(target) || 0
  const from = Number(display.value) || 0
  const diff = t - from
  if (Math.abs(diff) < 0.5) { display.value = t; return }
  const start = performance.now()
  function tick(now) {
    const p = Math.min((now - start) / props.duration, 1)
    const eased = 1 - Math.pow(1 - p, 3) // easeOutCubic
    display.value = from + diff * eased
    if (p < 1) raf = requestAnimationFrame(tick)
    else display.value = t
  }
  raf = requestAnimationFrame(tick)
}

onMounted(() => animateTo(props.value))
watch(() => props.value, (v) => animateTo(v))
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <span class="count-up">
    {{ props.format ? Math.round(display).toLocaleString() : display.toFixed(props.decimals) }}
  </span>
</template>

<style scoped>
.count-up { font-variant-numeric: tabular-nums; }
</style>
