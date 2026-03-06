<script lang="ts">
	import SymbolSearch from '$lib/components/SymbolSearch.svelte';
	import { selectedUnderlying, fetchStatus, fetchUnderlying } from '$lib/stores';

	let { children } = $props();
	let symbol = $state('');

	function handleFetch() {
		if (!symbol) return;
		fetchUnderlying(symbol);
	}
</script>

<div class="app">
	<nav>
		<div class="nav-brand" title="OpenOptions — Options mispricing detection platform">OpenOptions</div>
		<div class="nav-links">
			<a href="/" title="Mispricing alerts — options where market IV deviates from the model, sorted by net edge">Dashboard</a>
			<a href="/surface" title="3D volatility surface — visualize market vs model IV across strikes and expiries">Vol Surface</a>
			<a href="/iv-crush" title="IV crush analysis — term structure, IV rank, ATM straddle pricing for short vol strategies">IV Crush</a>
			<a href="/contracts" title="Browse all option contracts — filter and sort">Contracts</a>
		</div>
		<div class="nav-fetch">
			<SymbolSearch bind:value={symbol} onsubmit={handleFetch} placeholder="Fetch symbol..." loading={$fetchStatus.loading} />
			<button onclick={handleFetch} disabled={$fetchStatus.loading || !symbol} class="fetch-btn">
				{$fetchStatus.loading ? 'Fetching...' : 'Fetch'}
			</button>
			{#if $fetchStatus.result}
				<span class="fetch-result">{$fetchStatus.result}</span>
			{/if}
			{#if $fetchStatus.error}
				<span class="fetch-error">{$fetchStatus.error}</span>
			{/if}
		</div>
	</nav>

	<main>
		{@render children()}
	</main>
</div>

<style>
	:global(body) {
		margin: 0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		background: #0f1117;
		color: #e1e4e8;
	}

	.app {
		min-height: 100vh;
	}

	nav {
		display: flex;
		align-items: center;
		gap: 2rem;
		padding: 0.75rem 1.5rem;
		background: #161b22;
		border-bottom: 1px solid #30363d;
	}

	.nav-brand {
		font-size: 1.25rem;
		font-weight: 700;
		color: #58a6ff;
	}

	.nav-links {
		display: flex;
		gap: 1rem;
	}

	.nav-links a {
		color: #8b949e;
		text-decoration: none;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
		transition: color 0.15s;
	}

	.nav-links a:hover {
		color: #e1e4e8;
	}

	.nav-fetch {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		margin-left: auto;
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
		white-space: nowrap;
	}

	.fetch-btn:hover:not(:disabled) { background: #2ea043; }
	.fetch-btn:disabled { opacity: 0.6; cursor: not-allowed; }

	.fetch-result { font-size: 0.75rem; color: #8b949e; white-space: nowrap; }
	.fetch-error { font-size: 0.75rem; color: #f85149; white-space: nowrap; }

	main {
		max-width: 1200px;
		margin: 0 auto;
		padding: 1.5rem;
	}
</style>
