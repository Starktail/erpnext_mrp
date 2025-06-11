<template>
  <div
    class="relative flex h-full flex-col justify-between transition-all duration-300 ease-in-out"
    :class="isSidebarCollapsed ? 'w-12' : 'w-[220px]'"
  >
    <div>
      <!-- Placeholder for UserDropdown or similar, if needed in the future -->
    </div>
    <div class="flex-1 overflow-y-auto">
      <div v-for="section in mrpSections" :key="section.name">
        <!-- Section Header -->
        <div
          v-if="!section.hideLabel && !isSidebarCollapsed"
          class="px-3 py-2 mt-2 text-xs font-semibold text-gray-500 uppercase tracking-wider"
        >
          {{ __(section.name) }}
        </div>
        <!-- Divider if collapsed and section has links -->
        <div
          v-if="!section.hideLabel && isSidebarCollapsed && section.links?.length"
          class="mx-2 my-2 h-px border-b border-gray-200"
        />

        <nav class="flex flex-col">
          <SidebarLink
            v-for="link in section.links"
            :key="link.label"
            :label="__(link.label)"
            :to="link.to"
            :isCollapsed="isSidebarCollapsed"
            class="mx-2 my-0.5"
          >
            <template #icon>
              <FeatherIcon :name="link.icon" class="h-4 w-4" />
            </template>
          </SidebarLink>
        </nav>
      </div>
    </div>
    <div class="m-2 flex flex-col gap-1">
      <!-- Placeholder for banners, help links, etc. -->
      <SidebarLink
        :label="isSidebarCollapsed ? __('Expand') : __('Collapse')"
        :isCollapsed="isSidebarCollapsed"
        @click="isSidebarCollapsed = !isSidebarCollapsed"
        class="my-0.5"
      >
        <template #icon>
          <FeatherIcon :name="isSidebarCollapsed ? 'chevrons-right' : 'chevrons-left'" class="h-4 w-4" />
        </template>
      </SidebarLink>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { useStorage } from '@vueuse/core';
import { FeatherIcon } from 'frappe-ui';
import SidebarLink from '@/components/SidebarLink.vue';

// Assumes __() is a global translation function.
// If not, you might need to import or define it.
// For example: const __ = (text) => text;

const isSidebarCollapsed = useStorage('mrp_isSidebarCollapsed', false);

const mrpSections = computed(() => [
  {
    name: 'Planning Tools',
    hideLabel: false,
    links: [
      {
        label: 'Material Requests',
        icon: 'list', // FeatherIcon name
        to: '/', // Assuming Home.vue (with MaterialRequestList) is at the root path
      },
      // Example of another link:
      // {
      //   label: 'Production Orders',
      //   icon: 'tool',
      //   to: '/production-orders',
      // },
    ],
  },
  // You can add more sections here, for example:
  // {
  //   name: 'Inventory Management',
  //   hideLabel: false,
  //   links: [
  //     { label: 'Stock Levels', icon: 'bar-chart-2', to: '/stock-levels' },
  //   ],
  // },
]);

// If __ is not globally available and you need a placeholder:
const __ = (text) => text;
</script>
