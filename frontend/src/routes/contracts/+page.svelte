<script lang="ts">
	import { api, type Contract } from '$lib/api';
	import { contracts, loadContracts } from '$lib/stores';
	import { onMount } from 'svelte';

	type SortKey = keyof Contract | 'dte';
	let sortKey = $state<SortKey>('expiry');
	let sortDir = $state<'asc' | 'desc'>('asc');
	let search = $state('');
	let filterUnderlying = $state('');
	let filterType = $state('');
	let filterWatchlisted = $state<string>('');

	onMount(() => {
		loadContracts({ underlying: undefined, watchlisted: undefined });
	});

	function getDte(expiry: string): number {
		const diff = new Date(expiry + 'T00:00:00').getTime() - new Date().getTime();
		return Math.max(0, Math.ceil(diff / 86400000));
	}

	function toggleSort(key: SortKey) {
		if (sortKey === key) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortDir = key === 'strike' || key === 'dte' ? 'asc' : key === 'symbol' || key === 'expiry' ? 'asc' : 'desc';
		}
	}

	function sortIndicator(key: SortKey): string {
		if (sortKey !== key) return '';
		return sortDir === 'asc' ? ' \u25B2' : ' \u25BC';
	}

	let filtered = $derived.by(() => {
		let items = $contracts.items;

		if (search) {
			const q = search.toLowerCase();
			items = items.filter(c => c.symbol.toLowerCase().includes(q));
		}
		if (filterUnderlying) {
			items = items.filter(c => c.underlying === filterUnderlying);
		}
		if (filterType) {
			items = items.filter(c => c.option_type === filterType);
		}
		if (filterWatchlisted === 'true') {
			items = items.filter(c => c.is_watchlisted);
		} else if (filterWatchlisted === 'false') {
			items = items.filter(c => !c.is_watchlisted);
		}

		const dir = sortDir === 'asc' ? 1 : -1;
		items = [...items].sort((a, b) => {
			const av = sortKey === 'dte' ? getDte(a.expiry) : a[sortKey as keyof Contract];
			const bv = sortKey === 'dte' ? getDte(b.expiry) : b[sortKey as keyof Contract];
			if (av == null && bv == null) return 0;
			if (av == null) return 1;
			if (bv == null) return -1;
			if (typeof av === 'string') return av.localeCompare(bv as string) * dir;
			if (typeof av === 'boolean') return ((av ? 1 : 0) - (bv as number)) * dir;
			return ((av as number) - (bv as number)) * dir;
		});

		return items;
	});

	let underlyings = $derived([...new Set($contracts.items.map(c => c.underlying))].sort());

	let toggling = $state<number | null>(null);

	async function toggleWatch(contract: Contract) {
		toggling = contract.id;
		try {
			if (contract.is_watchlisted) {
				await api.unwatchContract(contract.id);
			} else {
				await api.watchContract(contract.id);
			}
			await loadContracts();
		} finally {
			toggling = null;
		}
	}
</script>

<div class="contracts-page">
	<header>
		<h1>Contracts</h1>
	</header>

	<div class="controls">
		<input type="text" placeholder="Search symbol..." bind:value={search} class="search" title="Filter contracts by symbol name" />
		<select bind:value={filterUnderlying} title="Filter by underlying asset (e.g. BTC, ETH)">
			<option value="">All Underlyings</option>
			{#each underlyings as u}
				<option value={u}>{u}</option>
			{/each}
		</select>
		<select bind:value={filterType} title="Filter by option type — Calls (right to buy) or Puts (right to sell)">
			<option value="">Call + Put</option>
			<option value="C">Calls</option>
			<option value="P">Puts</option>
		</select>
		<select bind:value={filterWatchlisted} title="Filter by watchlist status — watchlisted contracts are tracked for alerts">
			<option value="">All</option>
			<option value="true">Watchlisted</option>
			<option value="false">Not Watchlisted</option>
		</select>
		<span class="count" title="Number of contracts shown after filters / total contracts">{filtered.length} of {$contracts.total}</span>
	</div>

	<div class="table-wrapper">
		<table>
			<thead>
				<tr>
					<th class="sortable" onclick={() => toggleSort('symbol')} title="Option contract ticker (e.g. BTC-27MAR26-85000-C). Click to sort.">Symbol{sortIndicator('symbol')}</th>
					<th class="sortable" onclick={() => toggleSort('underlying')} title="The base asset this option derives from (e.g. BTC, ETH). Click to sort.">Underlying{sortIndicator('underlying')}</th>
					<th class="sortable num" onclick={() => toggleSort('strike')} title="Strike price — the price at which the option can be exercised, in USD. Click to sort.">Strike{sortIndicator('strike')}</th>
					<th class="sortable" onclick={() => toggleSort('expiry')} title="Expiration date — when the option contract expires. Click to sort.">Expiry{sortIndicator('expiry')}</th>
					<th class="sortable num" onclick={() => toggleSort('dte')} title="Days to expiry — calendar days remaining. Click to sort.">DTE{sortIndicator('dte')}</th>
					<th class="sortable" onclick={() => toggleSort('option_type')} title="C = Call (right to buy the underlying), P = Put (right to sell). Click to sort.">Type{sortIndicator('option_type')}</th>
					<th title="Data source — the exchange providing market data (e.g. Deribit, Tradier)">Source</th>
					<th class="sortable" onclick={() => toggleSort('is_watchlisted')} title="Watchlist status — watchlisted contracts are actively monitored for mispricing alerts. Click ★/☆ to toggle.">Watch{sortIndicator('is_watchlisted')}</th>
				</tr>
			</thead>
			<tbody>
				{#each filtered as contract (contract.id)}
					{@const dte = getDte(contract.expiry)}
					<tr>
						<td class="mono">{contract.symbol}</td>
						<td>{contract.underlying}</td>
						<td class="num">{contract.strike.toLocaleString()}</td>
						<td>{contract.expiry}</td>
						<td class="num" class:dte-urgent={dte <= 3} class:dte-warn={dte > 3 && dte <= 7}>{dte}d</td>
						<td>{contract.option_type}</td>
						<td class="source">{contract.source}</td>
						<td>
							<button
								class="watch-btn"
								class:watched={contract.is_watchlisted}
								onclick={() => toggleWatch(contract)}
								disabled={toggling === contract.id}
								title={contract.is_watchlisted ? 'Remove from watchlist — stop monitoring for mispricing alerts' : 'Add to watchlist — monitor this contract for mispricing alerts'}
							>
								{contract.is_watchlisted ? '★' : '☆'}
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if $contracts.items.length === 0}
		<p class="empty">No contracts found. Fetch data first to populate contracts.</p>
	{:else if filtered.length === 0}
		<p class="empty">No contracts match your filters.</p>
	{/if}
</div>

<style>
	.contracts-page header {
		margin-bottom: 1rem;
	}

	h1 { font-size: 1.5rem; margin: 0; }

	.controls {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
		align-items: center;
		flex-wrap: wrap;
	}

	.search { width: 180px; }

	.count {
		color: #8b949e;
		font-size: 0.8rem;
		margin-left: auto;
	}

	input, select {
		background: #21262d;
		color: #c9d1d9;
		border: 1px solid #30363d;
		padding: 0.4rem 0.6rem;
		border-radius: 6px;
		font-size: 0.8rem;
	}

	.table-wrapper { overflow-x: auto; }

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}

	th {
		text-align: left;
		padding: 0.5rem 0.75rem;
		border-bottom: 2px solid #30363d;
		color: #8b949e;
		font-weight: 600;
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		white-space: nowrap;
	}

	th.sortable {
		cursor: pointer;
		user-select: none;
	}

	th.sortable:hover {
		color: #c9d1d9;
	}

	td {
		padding: 0.4rem 0.75rem;
		border-bottom: 1px solid #21262d;
	}

	tr:hover {
		background: #161b22;
	}

	.mono {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.78rem;
	}

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.source {
		color: #8b949e;
	}

	.watch-btn {
		background: none;
		border: 1px solid transparent;
		color: #484f58;
		padding: 0.15rem 0.4rem;
		border-radius: 4px;
		cursor: pointer;
		font-size: 1rem;
		line-height: 1;
	}

	.watch-btn:hover:not(:disabled) {
		color: #58a6ff;
	}

	.watch-btn.watched {
		color: #e3b341;
	}

	.watch-btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.dte-urgent { color: #f85149; font-weight: 600; }
	.dte-warn { color: #f0883e; }

	.empty { text-align: center; color: #8b949e; padding: 2rem; }
</style>
