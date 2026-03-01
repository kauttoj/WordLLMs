<template>
  <div class="relative w-full rounded-lg border border-border bg-bg-secondary shadow-sm" :class="p1 ? 'p-1' : 'p-4'">
    <slot></slot>
    <slot name="extra"></slot>
  </div>
</template>

<script setup lang="ts">
const { p1 = false } = defineProps<{
  p1?: boolean
}>()
</script>
