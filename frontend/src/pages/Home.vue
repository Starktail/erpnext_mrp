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
    <ListView
      :rows="$resources.material_requests.data || []"
      rowKey="name"
      :columns="columns"
      class="mt-8"
    />
  </div>
</template>

<script>
import { Dialog, Button, ListView, createListResource } from 'frappe-ui'

export default {
  name: 'Home',
  data() {
    return {
      showDialog: false,
      columns: [
        { key: 'name', label: 'Name' },
        { key: 'transaction_date', label: 'Transaction Date' },
        { key: 'status', label: 'Status' }
      ]
    }
  },
  resources: {
    ping: {
      url: 'ping',
    },
    material_requests() {
      return {
        type: 'list',
        doctype: 'Material Request',
        fields: ['name', 'title', 'status', 'transaction_date'],
        orderBy: 'creation desc',
        start: 0,
        pageLength: 5,
        auto: true,
      }
    },
  },
  methods: {
    goToFrappe() {
      window.open('/app', '_blank')
    }
  },
  components: {
    Dialog,
    Button,
    ListView,
  },
}
</script>
