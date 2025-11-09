<template>
	<div class="w-full px-4 py-12">
		<h1 class="text-2xl font-bold mb-4">Forecast</h1>
		<ForecastList class="mt-8" />
	</div>
</template>

<script>
import ForecastList from '@/components/ForecastList.vue'

export default {
	name: 'Forecast',
	components: {
		ForecastList,
	},
}
</script>
