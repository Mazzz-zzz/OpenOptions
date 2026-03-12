<script lang="ts">
	import { api, type FetchedUnderlying } from '$lib/api';
	import { addToast } from '$lib/stores';
	import { timeAgo } from '$lib/utils';
	import { onMount } from 'svelte';

	let {
		value = $bindable(''),
		onsubmit,
		placeholder = 'Search symbol...',
		loading = false,
	}: {
		value: string;
		onsubmit?: () => void;
		placeholder?: string;
		loading?: boolean;
	} = $props();

	let inputEl: HTMLInputElement;
	let focused = $state(false);
	let fetched = $state<FetchedUnderlying[]>([]);

	onMount(async () => {
		try {
			const res = await api.getUnderlyings();
			fetched = res.data;
		} catch (e) {
			addToast('Failed to load symbols list', 'error');
		}
	});

	const POPULAR = [
		{ label: 'BTC', group: 'Crypto' },
		{ label: 'ETH', group: 'Crypto' },
		{ label: '/ES', group: 'Futures' },
		{ label: '/NQ', group: 'Futures' },
		{ label: '/CL', group: 'Futures' },
		{ label: '/GC', group: 'Futures' },
		{ label: 'SPY', group: 'Index ETF' },
		{ label: 'QQQ', group: 'Index ETF' },
		{ label: 'IWM', group: 'Index ETF' },
		{ label: 'AAPL', group: 'Equity' },
		{ label: 'MSFT', group: 'Equity' },
		{ label: 'NVDA', group: 'Equity' },
		{ label: 'TSLA', group: 'Equity' },
		{ label: 'AMZN', group: 'Equity' },
		{ label: 'META', group: 'Equity' },
		{ label: 'GOOGL', group: 'Equity' },
	];

	let fetchedSymbols = $derived(new Set(fetched.map(f => f.symbol)));

	let filtered = $derived(
		value.trim()
			? POPULAR.filter(s => s.label.toLowerCase().includes(value.toLowerCase()))
			: POPULAR
	);

	function select(sym: string) {
		value = sym;
		focused = false;
		inputEl?.blur();
		onsubmit?.();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			value = value.trim().toUpperCase();
			if (value) {
				focused = false;
				inputEl?.blur();
				onsubmit?.();
			}
		}
		if (e.key === 'Escape') {
			focused = false;
			inputEl?.blur();
		}
	}
</script>

<div class="search-wrapper">
	<div class="search-input" class:focused>
		<svg class="search-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
			<path fill="var(--text-muted, #8b949e)" d="M10.68 11.74a6 6 0 0 1-7.92-8.98 6 6 0 0 1 8.98 7.92l3.81 3.81a.75.75 0 0 1-1.06 1.06l-3.81-3.81zM6 10.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9z"/>
		</svg>
		<input
			bind:this={inputEl}
			bind:value
			onfocus={() => focused = true}
			onblur={() => setTimeout(() => focused = false, 150)}
			onkeydown={handleKeydown}
			{placeholder}
			disabled={loading}
			spellcheck="false"
			autocomplete="off"
		/>
		{#if value}
			<button class="clear" onclick={() => { value = ''; inputEl?.focus(); }} title="Clear" aria-label="Clear search">
				<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
					<path fill="var(--text-muted, #8b949e)" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
				</svg>
			</button>
		{/if}
	</div>

	{#if focused}
		<div class="dropdown">
			{#if fetched.length > 0}
				<div class="group-label">Previously fetched</div>
				{#each fetched as u}
					{@const matches = !value.trim() || u.symbol.toLowerCase().includes(value.toLowerCase())}
					{#if matches}
						<button
							class="dropdown-item fetched-item"
							class:active={value.toUpperCase() === u.symbol}
							onmousedown={(e) => { e.preventDefault(); select(u.symbol); }}
						>
							<span class="sym">{u.symbol}</span>
							{#if u.last_fetched_at}
								<span class="meta">{timeAgo(u.last_fetched_at)}</span>
							{/if}
						</button>
					{/if}
				{/each}
			{/if}

			{#each ['Crypto', 'Futures', 'Index ETF', 'Equity'] as group}
				{@const items = filtered.filter(s => s.group === group && !fetchedSymbols.has(s.label))}
				{#if items.length > 0}
					<div class="group-label">{group}</div>
					{#each items as item}
						<button
							class="dropdown-item"
							class:active={value.toUpperCase() === item.label}
							onmousedown={(e) => { e.preventDefault(); select(item.label); }}
						>
							{item.label}
						</button>
					{/each}
				{/if}
			{/each}
			{#if value.trim() && !POPULAR.some(s => s.label === value.trim().toUpperCase()) && !fetchedSymbols.has(value.trim().toUpperCase())}
				<div class="group-label">Custom</div>
				<button
					class="dropdown-item custom"
					onmousedown={(e) => { e.preventDefault(); select(value.trim().toUpperCase()); }}
				>
					Load <strong>{value.trim().toUpperCase()}</strong>
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.search-wrapper {
		position: relative;
	}

	.search-input {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		background: var(--bg-input);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 0 0.6rem;
		transition: border-color 0.15s;
	}

	.search-input.focused {
		border-color: var(--blue);
		box-shadow: 0 0 0 3px rgba(9, 105, 218, 0.12);
	}

	.search-icon {
		flex-shrink: 0;
	}

	input {
		background: transparent;
		border: none;
		outline: none;
		color: var(--text);
		font-size: 0.875rem;
		padding: 0.5rem 0;
		width: 140px;
		font-family: inherit;
	}

	input::placeholder {
		color: var(--text-muted);
	}

	input:disabled {
		opacity: 0.6;
	}

	.clear {
		background: none;
		border: none;
		cursor: pointer;
		padding: 2px;
		display: flex;
		align-items: center;
		opacity: 0.6;
	}

	.clear:hover { opacity: 1; }

	.dropdown {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		width: 220px;
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 0.25rem 0;
		z-index: 100;
		box-shadow: var(--shadow-md);
		max-height: 360px;
		overflow-y: auto;
	}

	.group-label {
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-muted);
		padding: 0.4rem 0.75rem 0.15rem;
		font-weight: 600;
	}

	.dropdown-item {
		display: block;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		color: var(--text);
		padding: 0.35rem 0.75rem;
		font-size: 0.8rem;
		cursor: pointer;
		font-family: inherit;
	}

	.dropdown-item:hover {
		background: var(--hover-bg);
	}

	.dropdown-item.active {
		color: var(--blue);
		font-weight: 600;
	}

	.dropdown-item.custom {
		color: var(--text-secondary);
	}

	.dropdown-item.custom strong {
		color: var(--blue);
	}

	.fetched-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.fetched-item .sym {
		font-weight: 600;
	}

	.fetched-item .meta {
		font-size: 0.65rem;
		color: var(--text-muted);
	}
</style>
