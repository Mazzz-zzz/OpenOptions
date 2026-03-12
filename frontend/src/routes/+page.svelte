<script lang="ts">
	import AlertTable from '$lib/components/AlertTable.svelte';
	import { alerts } from '$lib/stores';
	import { onMount } from 'svelte';

	onMount(() => {
		alerts.refresh();
	});
</script>

<div class="dashboard">
	<header>
		<h1>Mispricing Dashboard</h1>
	</header>

	{#if $alerts.loading && $alerts.items.length === 0}
		<p class="status">Loading alerts...</p>
	{/if}

	<AlertTable />
</div>

<style>
	.dashboard header {
		margin-bottom: 1.5rem;
	}

	h1 {
		font-size: 1.5rem;
		font-weight: 600;
		margin: 0;
	}

	.status { text-align: center; color: var(--text-secondary); padding: 2rem; }
</style>
