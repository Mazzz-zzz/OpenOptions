<script lang="ts">
	import SymbolSearch from '$lib/components/SymbolSearch.svelte';
	import AlertTable from '$lib/components/AlertTable.svelte';
	import { api } from '$lib/api';
	import { alerts } from '$lib/stores';
	import { onMount } from 'svelte';

	let symbol = $state('');
	let loading = $state(false);
	let result = $state<{ snapshots: number; alerts_raised: number; source?: string } | null>(null);
	let error = $state<string | null>(null);

	onMount(() => {
		alerts.refresh();
	});

	async function fetchSymbol() {
		if (!symbol) return;
		loading = true;
		error = null;
		result = null;
		try {
			result = await api.fetchChain(symbol);
			await alerts.refresh();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Fetch failed';
		} finally {
			loading = false;
		}
	}
</script>

<div class="dashboard">
	<header>
		<h1>Mispricing Dashboard</h1>
		<div class="fetch-controls">
			<SymbolSearch bind:value={symbol} onsubmit={fetchSymbol} placeholder="Fetch symbol..." {loading} />
			<button onclick={fetchSymbol} disabled={loading || !symbol} class="fetch-btn">
				{loading ? 'Fetching...' : 'Fetch'}
			</button>
			{#if result}
				<span class="result">{result.alerts_raised} alerts / {result.snapshots} contracts</span>
			{/if}
			{#if error}
				<span class="error">{error}</span>
			{/if}
		</div>
	</header>

	{#if $alerts.loading && $alerts.items.length === 0}
		<p class="status">Loading alerts...</p>
	{/if}

	<AlertTable />
</div>

<style>
	.dashboard header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1.5rem;
		flex-wrap: wrap;
		gap: 0.75rem;
	}

	h1 {
		font-size: 1.5rem;
		font-weight: 600;
		margin: 0;
	}

	.fetch-controls {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.fetch-btn {
		background: #238636;
		color: white;
		border: none;
		padding: 0.5rem 1rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.875rem;
		font-weight: 500;
		transition: background 0.15s;
	}

	.fetch-btn:hover:not(:disabled) { background: #2ea043; }
	.fetch-btn:disabled { opacity: 0.6; cursor: not-allowed; }

	.result { font-size: 0.8rem; color: #8b949e; }
	.error { font-size: 0.8rem; color: #f85149; }
	.status { text-align: center; color: #8b949e; padding: 2rem; }
</style>
