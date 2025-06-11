<template>
  <router-link
    :to="to"
    class="flex items-center px-3 py-2 text-sm font-medium rounded-md hover:bg-gray-200 dark:hover:bg-gray-700 group"
    :class="{ 'justify-center': isCollapsed }"
    active-class="bg-gray-300 dark:bg-gray-600 text-gray-900 dark:text-white font-semibold"
    inactive-class="text-gray-700 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
  >
    <span :class="{ 'mr-3': !isCollapsed }" class="flex-shrink-0 h-5 w-5">
      <slot name="icon"></slot>
    </span>
    <span v-if="!isCollapsed" class="truncate flex-grow">
      {{ label }}
    </span>
    <span
      v-if="isCollapsed"
      class="absolute left-full ml-2 p-1 px-2 py-1 text-xs font-medium text-white bg-gray-800 rounded-md opacity-0 group-hover:opacity-100 whitespace-nowrap z-10"
      style="pointer-events: none;"
    >
      {{ label }} <!-- Tooltip for collapsed state -->
    </span>
  </router-link>
</template>

<script setup>
import { RouterLink } from 'vue-router';

defineProps({
  to: {
    type: [String, Object],
    required: true,
  },
  label: {
    type: String,
    required: true,
  },
  isCollapsed: {
    type: Boolean,
    default: false,
  },
});
</script>
