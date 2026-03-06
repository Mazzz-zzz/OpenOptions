<script lang="ts">
	import VolSurface from '$lib/components/VolSurface.svelte';
	import { surface, loadSurface, selectedUnderlying } from '$lib/stores';

	let selectedType = $state('C');
	let loading = $state(false);
	let error = $state<string | null>(null);

	async function load(underlying: string) {
		if (!underlying) return;
		loading = true;
		error = null;
		try {
			await loadSurface(underlying, selectedType || undefined);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load surface';
		} finally {
			loading = false;
		}
	}

	// React to global symbol changes
	$effect(() => {
		const sym = $selectedUnderlying;
		if (sym) load(sym);
	});
</script>

<div class="surface-page">
	<header>
		<h1 title="3D visualization of implied volatility across strikes and expiries — highlights where market IV diverges from the fitted model">Volatility Surface</h1>
		<div class="controls">
			{#if $selectedUnderlying}
				<span class="current-symbol">{$selectedUnderlying}</span>
			{:else}
				<span class="hint">Fetch a symbol from the navbar</span>
			{/if}
			<div class="type-toggle" title="View calls or puts separately — mixing them creates overlapping surfaces with different skew profiles">
				<button class:active={selectedType === 'C'} onclick={() => { selectedType = 'C'; if ($selectedUnderlying) load($selectedUnderlying); }}>Calls</button>
				<button class:active={selectedType === 'P'} onclick={() => { selectedType = 'P'; if ($selectedUnderlying) load($selectedUnderlying); }}>Puts</button>
				<button class:active={selectedType === ''} onclick={() => { selectedType = ''; if ($selectedUnderlying) load($selectedUnderlying); }}>Both</button>
			</div>
			{#if loading}
				<span class="loading">Loading...</span>
			{/if}
		</div>
	</header>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if $surface}
		<VolSurface surfaceData={$surface} />
	{:else if !loading}
		<p class="placeholder">Fetch a symbol from the navbar to view the volatility surface.</p>
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

	.current-symbol {
		background: #388bfd26;
		color: #58a6ff;
		padding: 0.35rem 0.75rem;
		border-radius: 6px;
		font-weight: 600;
		font-size: 0.875rem;
	}

	.hint {
		color: #484f58;
		font-size: 0.8rem;
	}

	.loading {
		color: #8b949e;
		font-size: 0.8rem;
	}

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
