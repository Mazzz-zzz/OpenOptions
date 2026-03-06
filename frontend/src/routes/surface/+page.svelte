<script lang="ts">
	import VolSurface from '$lib/components/VolSurface.svelte';
	import SymbolSearch from '$lib/components/SymbolSearch.svelte';
	import { surface, loadSurface } from '$lib/stores';

	let selectedUnderlying = $state('BTC');
	let selectedType = $state('C');
	let loading = $state(false);
	let error = $state<string | null>(null);

	async function load() {
		if (!selectedUnderlying) return;
		loading = true;
		error = null;
		try {
			await loadSurface(selectedUnderlying, selectedType || undefined);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load surface';
		} finally {
			loading = false;
		}
	}
</script>

<div class="surface-page">
	<header>
		<h1 title="3D visualization of implied volatility across strikes and expiries — highlights where market IV diverges from the fitted model">Volatility Surface</h1>
		<div class="controls">
			<SymbolSearch bind:value={selectedUnderlying} onsubmit={load} placeholder="Symbol..." {loading} />
			<div class="type-toggle" title="View calls or puts separately — mixing them creates overlapping surfaces with different skew profiles">
				<button class:active={selectedType === 'C'} onclick={() => selectedType = 'C'}>Calls</button>
				<button class:active={selectedType === 'P'} onclick={() => selectedType = 'P'}>Puts</button>
				<button class:active={selectedType === ''} onclick={() => selectedType = ''}>Both</button>
			</div>
			<button onclick={load} disabled={loading} class="load-btn" title="Load the latest volatility surface data — fits an SVI model to market IVs and compares market vs model across all strikes/expiries">
				{loading ? 'Loading...' : 'Load Surface'}
			</button>
		</div>
	</header>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if $surface}
		<VolSurface surfaceData={$surface} />
	{:else if !loading}
		<p class="placeholder">Select an underlying and click Load Surface to view the vol surface.</p>
	{/if}
</div>

<style>
	.surface-page header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1rem;
	}

	h1 {
		font-size: 1.5rem;
		margin: 0;
	}

	.controls {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	select, .load-btn {
		background: #21262d;
		color: #c9d1d9;
		border: 1px solid #30363d;
		padding: 0.5rem 1rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.875rem;
	}

	.load-btn:hover:not(:disabled) { background: #30363d; }
	.load-btn:disabled { opacity: 0.6; cursor: not-allowed; }

	.type-toggle {
		display: flex;
		border: 1px solid #30363d;
		border-radius: 6px;
		overflow: hidden;
	}

	.type-toggle button {
		background: #21262d;
		color: #8b949e;
		border: none;
		border-right: 1px solid #30363d;
		padding: 0.5rem 0.75rem;
		font-size: 0.8rem;
		cursor: pointer;
		transition: all 0.15s;
	}

	.type-toggle button:last-child {
		border-right: none;
	}

	.type-toggle button.active {
		background: #388bfd26;
		color: #58a6ff;
	}

	.type-toggle button:hover:not(.active) {
		color: #c9d1d9;
	}

	.error { color: #f85149; }
	.placeholder { color: #8b949e; text-align: center; padding: 3rem; }
</style>
