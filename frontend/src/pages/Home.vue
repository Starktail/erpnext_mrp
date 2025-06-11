<template>
  <div class="max-w-3xl py-12 mx-auto">
    <Button
      icon-left="code"
      @click="$resources.ping.fetch"
      :loading="$resources.ping.loading"
    >
      Click to send 'ping' request
    </Button>
    <div>
      {{ $resources.ping.data }}
    </div>
    <pre>{{ $resources.ping }}</pre>

    <Button @click="showDialog = true">Open Dialog</Button>
    <Dialog title="Title" v-model="showDialog"> Dialog content </Dialog>
    <Button variant="primary" @click="goToFrappe">Open Frappe App</Button>
    <MaterialRequestList class="mt-8" />
  </div>
</template>

<script>
import { Dialog, Button } from 'frappe-ui';
import MaterialRequestList from '@/components/MaterialRequestList.vue';

export default {
  name: 'Home',
  data() {
    return {
      showDialog: false,
    };
  },
  resources: {
    ping: {
      url: 'ping',
    },
  },
  methods: {
    goToFrappe() {
      window.open('/app', '_blank');
    },
  },
  components: {
    Dialog,
    Button,
    MaterialRequestList,
  },
};
</script>
