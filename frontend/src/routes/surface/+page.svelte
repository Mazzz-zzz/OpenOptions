<script lang="ts">
	import VolSurface from '$lib/components/VolSurface.svelte';
	import { surface, loadSurface, selectedUnderlying, addToast } from '$lib/stores';

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
			const msg = e instanceof Error ? e.message : 'Failed to load surface';
			error = msg;
			addToast(msg, 'error');
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		const sym = $selectedUnderlying;
		if (sym) load(sym);
	});
</script>

<div class="surface-page">
	<header>
		<h1>Volatility Surface</h1>
		<div class="controls">
			{#if $selectedUnderlying}
				<span class="current-symbol">{$selectedUnderlying}</span>
			{:else}
				<span class="hint">Fetch a symbol from the navbar</span>
			{/if}
			<div class="type-toggle">
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
		background: var(--badge-blue);
		color: var(--blue);
		padding: 0.35rem 0.75rem;
		border-radius: 6px;
		font-weight: 600;
		font-size: 0.875rem;
	}

	.hint {
		color: var(--text-muted);
		font-size: 0.8rem;
	}

	.loading {
		color: var(--text-secondary);
		font-size: 0.8rem;
	}

	.type-toggle {
		display: flex;
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}

	.type-toggle button {
		background: var(--bg-input);
		color: var(--text-secondary);
		border: none;
		border-right: 1px solid var(--border);
		padding: 0.5rem 0.75rem;
		font-size: 0.8rem;
		cursor: pointer;
		transition: all 0.15s;
	}

	.type-toggle button:last-child {
		border-right: none;
	}

	.type-toggle button.active {
		background: var(--badge-blue);
		color: var(--blue);
	}

	.type-toggle button:hover:not(.active) {
		color: var(--text);
	}

	.error { color: var(--red); }
	.placeholder { color: var(--text-secondary); text-align: center; padding: 3rem; }
</style>
