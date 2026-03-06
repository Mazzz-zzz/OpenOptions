<script lang="ts">
	import { api, type FetchedUnderlying } from '$lib/api';
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
		} catch {}
	});

	const POPULAR = [
		{ label: 'BTC', group: 'Crypto' },
		{ label: 'ETH', group: 'Crypto' },
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

	function timeAgo(iso: string): string {
		const diff = Date.now() - new Date(iso).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		const days = Math.floor(hrs / 24);
		return `${days}d ago`;
	}
</script>

<div class="search-wrapper">
	<div class="search-input" class:focused>
		<svg class="search-icon" viewBox="0 0 16 16" width="14" height="14">
			<path fill="#8b949e" d="M10.68 11.74a6 6 0 0 1-7.92-8.98 6 6 0 0 1 8.98 7.92l3.81 3.81a.75.75 0 0 1-1.06 1.06l-3.81-3.81zM6 10.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9z"/>
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
			<button class="clear" onclick={() => { value = ''; inputEl?.focus(); }} title="Clear">
				<svg viewBox="0 0 16 16" width="12" height="12">
					<path fill="#8b949e" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
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

			{#each ['Crypto', 'Index ETF', 'Equity'] as group}
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
		background: #21262d;
		border: 1px solid #30363d;
		border-radius: 6px;
		padding: 0 0.6rem;
		transition: border-color 0.15s;
	}

	.search-input.focused {
		border-color: #58a6ff;
	}

	.search-icon {
		flex-shrink: 0;
	}

	input {
		background: transparent;
		border: none;
		outline: none;
		color: #e1e4e8;
		font-size: 0.875rem;
		padding: 0.5rem 0;
		width: 140px;
		font-family: inherit;
	}

	input::placeholder {
		color: #484f58;
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
		background: #1c2128;
		border: 1px solid #30363d;
		border-radius: 8px;
		padding: 0.25rem 0;
		z-index: 100;
		box-shadow: 0 8px 24px rgba(0,0,0,0.4);
		max-height: 360px;
		overflow-y: auto;
	}

	.group-label {
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #484f58;
		padding: 0.4rem 0.75rem 0.15rem;
		font-weight: 600;
	}

	.dropdown-item {
		display: block;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		color: #c9d1d9;
		padding: 0.35rem 0.75rem;
		font-size: 0.8rem;
		cursor: pointer;
		font-family: inherit;
	}

	.dropdown-item:hover {
		background: #30363d;
	}

	.dropdown-item.active {
		color: #58a6ff;
		font-weight: 600;
	}

	.dropdown-item.custom {
		color: #8b949e;
	}

	.dropdown-item.custom strong {
		color: #58a6ff;
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
		color: #484f58;
	}
</style>
