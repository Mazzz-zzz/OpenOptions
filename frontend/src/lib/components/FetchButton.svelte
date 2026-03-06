<script lang="ts">
	import { api } from '$lib/api';
	import { alerts } from '$lib/stores';

	let { symbol }: { symbol: string } = $props();
	let loading = $state(false);
	let result = $state<{ snapshots: number; alerts_raised: number } | null>(null);
	let error = $state<string | null>(null);

	async function fetchNow() {
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

<div class="fetch-btn-wrapper">
	<button onclick={fetchNow} disabled={loading} class="fetch-btn" title="Fetch the latest {symbol} option chain from the exchange, compute model IV, greeks, and scan for mispricing alerts">
		{loading ? 'Fetching...' : `Fetch ${symbol}`}
	</button>

	{#if result}
		<span class="result" title="Number of new mispricing alerts detected / total option contracts fetched">
			{result.alerts_raised} alerts / {result.snapshots} contracts
		</span>
	{/if}

	{#if error}
		<span class="error" title="Error details from the fetch operation">{error}</span>
	{/if}
</div>

<style>
	.fetch-btn-wrapper {
		display: flex;
		align-items: center;
		gap: 0.5rem;
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

	.fetch-btn:hover:not(:disabled) {
		background: #2ea043;
	}

	.fetch-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.result {
		font-size: 0.8rem;
		color: #8b949e;
	}

	.error {
		font-size: 0.8rem;
		color: #f85149;
	}
</style>
