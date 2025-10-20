<template>
  <div class="flex h-screen bg-gray-100">
    <AppSidebar />
    <main class="flex-1 overflow-x-hidden overflow-hidden bg-gray-200">
      <div class="p-6 h-full">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import AppSidebar from '@/components/AppSidebar.vue';
</script>
