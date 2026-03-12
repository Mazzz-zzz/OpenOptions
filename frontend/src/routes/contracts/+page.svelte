<script lang="ts">
	import { type Contract } from '$lib/api';
	import { contracts, loadContracts, selectedUnderlying, addToast } from '$lib/stores';
	import { getDte } from '$lib/utils';
	import { onMount } from 'svelte';

	type SortKey = keyof Contract | 'dte';
	let sortKey = $state<SortKey>('expiry');
	let sortDir = $state<'asc' | 'desc'>('asc');
	let search = $state('');
	let filterUnderlying = $state('');
	let filterType = $state('');

	onMount(async () => {
		try {
			await loadContracts();
		} catch (e) {
			addToast('Failed to load contracts', 'error');
		}
	});

	$effect(() => {
		const sym = $selectedUnderlying;
		if (sym) {
			loadContracts({ underlying: sym }).catch(() => addToast('Failed to load contracts', 'error'));
		}
	});

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

		const dir = sortDir === 'asc' ? 1 : -1;
		items = [...items].sort((a, b) => {
			const av = sortKey === 'dte' ? getDte(a.expiry) : a[sortKey as keyof Contract];
			const bv = sortKey === 'dte' ? getDte(b.expiry) : b[sortKey as keyof Contract];
			if (av == null && bv == null) return 0;
			if (av == null) return 1;
			if (bv == null) return -1;
			if (typeof av === 'string') return av.localeCompare(bv as string) * dir;
			return ((av as number) - (bv as number)) * dir;
		});

		return items;
	});

	let underlyings = $derived([...new Set($contracts.items.map(c => c.underlying))].sort());
</script>

<div class="contracts-page">
	<header>
		<h1>Contracts</h1>
	</header>

	<div class="controls">
		<input type="text" placeholder="Search symbol..." bind:value={search} class="search" />
		<select bind:value={filterUnderlying}>
			<option value="">All Underlyings</option>
			{#each underlyings as u}
				<option value={u}>{u}</option>
			{/each}
		</select>
		<select bind:value={filterType}>
			<option value="">Call + Put</option>
			<option value="C">Calls</option>
			<option value="P">Puts</option>
		</select>
		<span class="count">{filtered.length} of {$contracts.total}</span>
	</div>

	<div class="table-wrapper">
		<table>
			<thead>
				<tr>
					<th class="sortable" onclick={() => toggleSort('symbol')}>Symbol{sortIndicator('symbol')}</th>
					<th class="sortable" onclick={() => toggleSort('underlying')}>Underlying{sortIndicator('underlying')}</th>
					<th class="sortable num" onclick={() => toggleSort('strike')}>Strike{sortIndicator('strike')}</th>
					<th class="sortable" onclick={() => toggleSort('expiry')}>Expiry{sortIndicator('expiry')}</th>
					<th class="sortable num" onclick={() => toggleSort('dte')}>DTE{sortIndicator('dte')}</th>
					<th class="sortable" onclick={() => toggleSort('option_type')}>Type{sortIndicator('option_type')}</th>
					<th>Source</th>
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
		color: var(--text-secondary);
		font-size: 0.8rem;
		margin-left: auto;
	}

	input, select {
		background: var(--bg-input);
		color: var(--text);
		border: 1px solid var(--border);
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
		border-bottom: 2px solid var(--border);
		color: var(--text-secondary);
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
		color: var(--text);
	}

	td {
		padding: 0.4rem 0.75rem;
		border-bottom: 1px solid var(--border-light);
	}

	tr:hover {
		background: var(--hover-bg);
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
		color: var(--text-secondary);
	}

	.dte-urgent { color: var(--red); font-weight: 600; }
	.dte-warn { color: var(--orange); }

	.empty { text-align: center; color: var(--text-secondary); padding: 2rem; }
</style>
