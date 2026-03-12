<script lang="ts">
	import { alerts, addToast } from '$lib/stores';
	import { api, type Alert } from '$lib/api';
	import { getDte, formatIv, formatDeviation, formatDollar, formatGreek } from '$lib/utils';

	type SortKey = keyof Alert | 'dte' | 'spread';
	let sortKey = $state<SortKey>('net_edge');
	let sortDir = $state<'asc' | 'desc'>('desc');
	let search = $state('');
	let filterSignal = $state('');
	let filterUnderlying = $state('');
	let filterConfidence = $state('');

	async function dismiss(id: number) {
		try {
			await api.dismissAlert(id);
			await alerts.refresh();
		} catch (e) {
			addToast('Failed to dismiss alert', 'error');
		}
	}

	function toggleSort(key: SortKey) {
		if (sortKey === key) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortDir = key === 'symbol' || key === 'expiry' || key === 'dte' ? 'asc' : 'desc';
		}
	}

	function sortIndicator(key: SortKey): string {
		if (sortKey !== key) return '';
		return sortDir === 'asc' ? ' \u25B2' : ' \u25BC';
	}

	function getSpread(alert: Alert): number | null {
		if (alert.bid === null || alert.ask === null) return null;
		return alert.ask - alert.bid;
	}

	function sortValue(alert: Alert, key: SortKey): string | number | boolean | null {
		if (key === 'dte') return getDte(alert.expiry);
		if (key === 'spread') return getSpread(alert);
		return alert[key as keyof Alert] as string | number | boolean | null;
	}

	let filtered = $derived.by(() => {
		let items = $alerts.items;

		if (search) {
			const q = search.toLowerCase();
			items = items.filter(a => a.symbol.toLowerCase().includes(q));
		}
		if (filterSignal) {
			items = items.filter(a => a.signal_type === filterSignal);
		}
		if (filterUnderlying) {
			items = items.filter(a => a.underlying === filterUnderlying);
		}
		if (filterConfidence) {
			items = items.filter(a => a.confidence === filterConfidence);
		}

		const dir = sortDir === 'asc' ? 1 : -1;
		items = [...items].sort((a, b) => {
			const av = sortValue(a, sortKey);
			const bv = sortValue(b, sortKey);
			if (av == null && bv == null) return 0;
			if (av == null) return 1;
			if (bv == null) return -1;
			if (typeof av === 'string') return av.localeCompare(bv as string) * dir;
			return ((av as number) - (bv as number)) * dir;
		});

		return items;
	});

	let underlyings = $derived([...new Set($alerts.items.map(a => a.underlying))].sort());
</script>

<div class="controls">
	<input type="text" placeholder="Search symbol..." bind:value={search} class="search" title="Filter alerts by contract symbol name" />
	<select bind:value={filterUnderlying} title="Filter by underlying asset">
		<option value="">All Underlyings</option>
		{#each underlyings as u}
			<option value={u}>{u}</option>
		{/each}
	</select>
	<select bind:value={filterSignal} title="Filter by detection method">
		<option value="">All Signals</option>
		<option value="surface_outlier">Surface Outlier</option>
		<option value="greek_divergence">Greek Divergence</option>
	</select>
	<select bind:value={filterConfidence} title="Filter by confidence level">
		<option value="">All Confidence</option>
		<option value="high">High</option>
		<option value="medium">Medium</option>
		<option value="low">Low</option>
	</select>
	<span class="count">{filtered.length} of {$alerts.items.length}</span>
</div>

<div class="table-wrapper">
	<table>
		<thead>
			<tr>
				<th class="sortable" onclick={() => toggleSort('symbol')}>Symbol{sortIndicator('symbol')}</th>
				<th class="sortable num" onclick={() => toggleSort('strike')}>Strike{sortIndicator('strike')}</th>
				<th class="sortable" onclick={() => toggleSort('expiry')}>Expiry{sortIndicator('expiry')}</th>
				<th class="sortable num" onclick={() => toggleSort('dte')}>DTE{sortIndicator('dte')}</th>
				<th>Type</th>
				<th>Signal</th>
				<th class="sortable" onclick={() => toggleSort('confidence')}>Conf{sortIndicator('confidence')}</th>
				<th class="sortable num" onclick={() => toggleSort('market_iv')}>Mkt IV{sortIndicator('market_iv')}</th>
				<th class="sortable num" onclick={() => toggleSort('model_iv')}>Mdl IV{sortIndicator('model_iv')}</th>
				<th class="sortable num" onclick={() => toggleSort('deviation')}>Dev{sortIndicator('deviation')}</th>
				<th class="sortable num" onclick={() => toggleSort('spread')}>Spread{sortIndicator('spread')}</th>
				<th class="sortable num" onclick={() => toggleSort('net_edge')}>Edge ($){sortIndicator('net_edge')}</th>
				<th class="sortable num" onclick={() => toggleSort('gamma')}>&Gamma;{sortIndicator('gamma')}</th>
				<th class="sortable num" onclick={() => toggleSort('theta')}>&Theta;{sortIndicator('theta')}</th>
				<th><span class="sr-only">Dismiss</span></th>
			</tr>
		</thead>
		<tbody>
			{#each filtered as alert (alert.id)}
				{@const dte = getDte(alert.expiry)}
				{@const spread = getSpread(alert)}
				<tr>
					<td class="mono">{alert.symbol}</td>
					<td class="num">{alert.strike.toLocaleString()}</td>
					<td>{alert.expiry}</td>
					<td class="num" class:dte-urgent={dte <= 3} class:dte-warn={dte > 3 && dte <= 7}>{dte}d</td>
					<td>{alert.option_type}</td>
					<td>
						<span class="badge" class:surface={alert.signal_type === 'surface_outlier'} class:greek={alert.signal_type === 'greek_divergence'}>
							{alert.signal_type === 'surface_outlier' ? 'Srf' : 'Grk'}
						</span>
					</td>
					<td>
						{#if alert.confidence}
							<span class="conf-badge conf-{alert.confidence}">{alert.confidence}</span>
						{:else}
							<span class="conf-badge conf-low">{'\u2014'}</span>
						{/if}
					</td>
					<td class="num">{formatIv(alert.market_iv, 2)}</td>
					<td class="num">{formatIv(alert.model_iv, 2)}</td>
					<td class="num" class:positive={alert.deviation !== null && alert.deviation > 0} class:negative={alert.deviation !== null && alert.deviation < 0}>
						{formatDeviation(alert.deviation)}
					</td>
					<td class="num spread" class:wide-spread={spread !== null && alert.net_edge !== null && spread > alert.net_edge * 2}>
						{spread !== null ? formatDollar(spread) : '\u2014'}
					</td>
					<td class="num edge">{formatDollar(alert.net_edge)}</td>
					<td class="num greek">{formatGreek(alert.gamma, 6)}</td>
					<td class="num greek" class:negative={alert.theta !== null && alert.theta < 0}>
						{alert.theta !== null ? formatDollar(alert.theta) : '\u2014'}
					</td>
					<td>
						<button class="dismiss-btn" onclick={() => dismiss(alert.id)} title="Dismiss" aria-label="Dismiss alert">&#x2715;</button>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>

	{#if $alerts.items.length === 0}
		<p class="empty">No active alerts. Fetch a symbol to scan for mispricings.</p>
	{:else if filtered.length === 0}
		<p class="empty">No alerts match your filters.</p>
	{/if}
</div>

<style>
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
		font-size: 0.8rem;
	}

	th {
		text-align: left;
		padding: 0.4rem 0.5rem;
		border-bottom: 2px solid var(--border);
		color: var(--text-secondary);
		font-weight: 600;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		white-space: nowrap;
	}

	th.sortable { cursor: pointer; user-select: none; }
	th.sortable:hover { color: var(--text); }

	td {
		padding: 0.35rem 0.5rem;
		border-bottom: 1px solid var(--border-light);
	}

	tr:hover { background: var(--hover-bg); }

	.mono {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.73rem;
	}

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.positive { color: var(--green); }
	.negative { color: var(--red); }
	.edge { font-weight: 600; color: var(--orange); }

	.dte-urgent { color: var(--red); font-weight: 600; }
	.dte-warn { color: var(--orange); }

	.spread { color: var(--text-secondary); }
	.wide-spread { color: var(--red); }

	.greek { color: var(--text-secondary); font-size: 0.73rem; }

	.badge {
		display: inline-block;
		padding: 0.1rem 0.4rem;
		border-radius: 10px;
		font-size: 0.65rem;
		font-weight: 600;
	}

	.badge.surface {
		background: var(--badge-blue);
		color: var(--blue);
	}

	.badge.greek {
		background: var(--badge-orange);
		color: var(--orange);
	}

	.conf-badge {
		font-size: 0.65rem;
		font-weight: 600;
		padding: 0.1rem 0.35rem;
		border-radius: 4px;
	}

	.conf-high { color: var(--green); background: var(--badge-green); }
	.conf-medium { color: var(--orange); background: var(--badge-orange); }
	.conf-low { color: var(--text-secondary); background: var(--badge-muted); }

	.dismiss-btn {
		background: none;
		border: 1px solid transparent;
		color: var(--text-muted);
		padding: 0.1rem 0.3rem;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.75rem;
		line-height: 1;
	}

	.dismiss-btn:hover {
		border-color: var(--red);
		color: var(--red);
	}

	.empty {
		text-align: center;
		color: var(--text-secondary);
		padding: 2rem;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		border: 0;
	}
</style>
