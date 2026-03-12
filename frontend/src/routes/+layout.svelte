<script lang="ts">
	import SymbolSearch from '$lib/components/SymbolSearch.svelte';
	import Toast from '$lib/components/Toast.svelte';
	import { selectedUnderlying, fetchStatus, selectUnderlying, fetchUnderlying } from '$lib/stores';

	let { children } = $props();
	let symbol = $state('');

	function handleSelect() {
		if (!symbol) return;
		selectUnderlying(symbol);
	}

	function handleFetch() {
		if (!symbol) return;
		fetchUnderlying(symbol);
	}
</script>

<div class="app">
	<nav>
		<div class="nav-brand" title="OpenOptions — Options mispricing detection platform">OpenOptions</div>
		<div class="nav-links">
			<a href="/" title="Mispricing alerts">Dashboard</a>
			<a href="/surface" title="3D volatility surface">Vol Surface</a>
			<a href="/iv-crush" title="Volatility analysis">Vol Analysis</a>
			<a href="/contracts" title="Browse option contracts">Contracts</a>
			<a href="/ml" title="Numerai ML training dashboard">Numerai</a>
		</div>
		<div class="nav-fetch">
			<SymbolSearch bind:value={symbol} onsubmit={handleSelect} placeholder="Select symbol..." loading={$fetchStatus.loading} />
			{#if $selectedUnderlying}
				<span class="active-symbol" title="Currently loaded symbol">{$selectedUnderlying}</span>
			{/if}
			<button onclick={handleFetch} disabled={$fetchStatus.loading || !symbol} class="fetch-btn" title="Fetch fresh data from exchange API">
				{$fetchStatus.loading ? 'Fetching...' : 'Refresh'}
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

<Toast />

<style>
	:global(:root) {
		--bg-page: #f6f8fa;
		--bg-card: #ffffff;
		--bg-input: #f6f8fa;
		--bg-nav: #ffffff;
		--border: #d1d9e0;
		--border-light: #e1e4e8;
		--text: #1f2328;
		--text-secondary: #656d76;
		--text-muted: #8b949e;
		--blue: #0969da;
		--green: #1a7f37;
		--red: #cf222e;
		--orange: #bc4c00;
		--purple: #8250df;
		--yellow: #9a6700;
		--hover-bg: #f0f2f5;
		--badge-blue: rgba(9, 105, 218, 0.08);
		--badge-green: rgba(26, 127, 55, 0.08);
		--badge-orange: rgba(188, 76, 0, 0.08);
		--badge-red: rgba(207, 34, 46, 0.08);
		--badge-muted: rgba(101, 109, 118, 0.08);
		--shadow-sm: 0 1px 2px rgba(0,0,0,0.06);
		--shadow-md: 0 4px 12px rgba(0,0,0,0.08);
	}

	:global(body) {
		margin: 0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		background: var(--bg-page);
		color: var(--text);
	}

	.app {
		min-height: 100vh;
	}

	nav {
		display: flex;
		align-items: center;
		gap: 2rem;
		padding: 0.75rem 1.5rem;
		background: var(--bg-nav);
		border-bottom: 1px solid var(--border);
		box-shadow: var(--shadow-sm);
	}

	.nav-brand {
		font-size: 1.25rem;
		font-weight: 700;
		color: var(--blue);
	}

	.nav-links {
		display: flex;
		gap: 1rem;
	}

	.nav-links a {
		color: var(--text-secondary);
		text-decoration: none;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
		transition: color 0.15s;
	}

	.nav-links a:hover {
		color: var(--text);
	}

	.nav-fetch {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		margin-left: auto;
	}

	.active-symbol {
		background: var(--badge-blue);
		color: var(--blue);
		padding: 0.35rem 0.6rem;
		border-radius: 6px;
		font-weight: 600;
		font-size: 0.8rem;
	}

	.fetch-btn {
		background: #2da44e;
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

	.fetch-btn:hover:not(:disabled) { background: var(--green); }
	.fetch-btn:disabled { opacity: 0.6; cursor: not-allowed; }

	.fetch-result { font-size: 0.75rem; color: var(--text-secondary); white-space: nowrap; }
	.fetch-error { font-size: 0.75rem; color: var(--red); white-space: nowrap; }

	main {
		max-width: 1200px;
		margin: 0 auto;
		padding: 1.5rem;
	}
</style>
