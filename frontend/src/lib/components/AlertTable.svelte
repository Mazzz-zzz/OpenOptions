<script lang="ts">
	import { alerts } from '$lib/stores';
	import { api, type Alert } from '$lib/api';

	type SortKey = keyof Alert | 'dte' | 'spread';
	let sortKey = $state<SortKey>('net_edge');
	let sortDir = $state<'asc' | 'desc'>('desc');
	let search = $state('');
	let filterSignal = $state('');
	let filterUnderlying = $state('');
	let filterConfidence = $state('');

	async function dismiss(id: number) {
		await api.dismissAlert(id);
		await alerts.refresh();
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

	function getDte(expiry: string): number {
		const diff = new Date(expiry + 'T00:00:00').getTime() - new Date().getTime();
		return Math.max(0, Math.ceil(diff / 86400000));
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

	function formatIv(iv: number | null): string {
		if (iv === null) return '\u2014';
		return (iv * 100).toFixed(2) + '%';
	}

	function formatDeviation(dev: number | null): string {
		if (dev === null) return '\u2014';
		return (dev > 0 ? '+' : '') + (dev * 100).toFixed(2);
	}

	function formatDollar(val: number | null): string {
		if (val === null) return '\u2014';
		return '$' + val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}

	function formatGreek(val: number | null, decimals = 4): string {
		if (val === null) return '\u2014';
		return val.toFixed(decimals);
	}
</script>

<div class="controls">
	<input type="text" placeholder="Search symbol..." bind:value={search} class="search" title="Filter alerts by contract symbol name" />
	<select bind:value={filterUnderlying} title="Filter by underlying asset (e.g. BTC, ETH)">
		<option value="">All Underlyings</option>
		{#each underlyings as u}
			<option value={u}>{u}</option>
		{/each}
	</select>
	<select bind:value={filterSignal} title="Filter by detection method — Surface Outlier (IV vs fitted surface) or Greek Divergence (delta/vega mismatch)">
		<option value="">All Signals</option>
		<option value="surface_outlier">Surface Outlier</option>
		<option value="greek_divergence">Greek Divergence</option>
	</select>
	<select bind:value={filterConfidence} title="Filter by confidence level — based on deviation size and vega magnitude">
		<option value="">All Confidence</option>
		<option value="high">High</option>
		<option value="medium">Medium</option>
		<option value="low">Low</option>
	</select>
	<span class="count" title="Number of alerts shown after filters / total alerts">{filtered.length} of {$alerts.items.length}</span>
</div>

<div class="table-wrapper">
	<table>
		<thead>
			<tr>
				<th class="sortable" onclick={() => toggleSort('symbol')} title="Option contract ticker (e.g. BTC-27MAR26-85000-C). Click to sort.">Symbol{sortIndicator('symbol')}</th>
				<th class="sortable num" onclick={() => toggleSort('strike')} title="Strike price in USD. Click to sort.">Strike{sortIndicator('strike')}</th>
				<th class="sortable" onclick={() => toggleSort('expiry')} title="Expiration date. Click to sort.">Expiry{sortIndicator('expiry')}</th>
				<th class="sortable num" onclick={() => toggleSort('dte')} title="Days to expiry — calendar days until the option expires. Click to sort.">DTE{sortIndicator('dte')}</th>
				<th title="Option type: C = Call, P = Put">Type</th>
				<th title="Detection method: Surface = IV deviates from fitted vol surface; Greek = delta/vega divergence">Signal</th>
				<th class="sortable" onclick={() => toggleSort('confidence')} title="Signal confidence level. High = strong edge, Medium = moderate, Low = marginal. Click to sort.">Conf{sortIndicator('confidence')}</th>
				<th class="sortable num" onclick={() => toggleSort('market_iv')} title="Market Implied Volatility from the bid/ask mid price. Click to sort.">Mkt IV{sortIndicator('market_iv')}</th>
				<th class="sortable num" onclick={() => toggleSort('model_iv')} title="Model IV predicted by the fitted SVI volatility surface. Click to sort.">Mdl IV{sortIndicator('model_iv')}</th>
				<th class="sortable num" onclick={() => toggleSort('deviation')} title="Deviation = (market IV - model IV) x 100 vol points. Positive = rich, Negative = cheap. Click to sort.">Dev{sortIndicator('deviation')}</th>
				<th class="sortable num" onclick={() => toggleSort('spread')} title="Bid-Ask spread in USD. Wider spread = lower liquidity, harder to capture edge. Click to sort.">Spread{sortIndicator('spread')}</th>
				<th class="sortable num" onclick={() => toggleSort('net_edge')} title="Net Edge ($) = |deviation| x 100 x vega - half spread. Dollar profit after crossing the spread. Click to sort.">Edge ($){sortIndicator('net_edge')}</th>
				<th class="sortable num" onclick={() => toggleSort('gamma')} title="Gamma — rate of change of delta per $1 move in the underlying. Higher = more convexity risk. Click to sort.">&Gamma;{sortIndicator('gamma')}</th>
				<th class="sortable num" onclick={() => toggleSort('theta')} title="Theta — daily time decay in USD. Negative = option loses value each day. Click to sort.">&Theta;{sortIndicator('theta')}</th>
				<th title="Dismiss this alert"></th>
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
					<td class="num" class:dte-urgent={dte <= 3} class:dte-warn={dte > 3 && dte <= 7}
						title={`${dte} calendar days until expiry`}>{dte}d</td>
					<td>{alert.option_type}</td>
					<td>
						<span class="badge" class:surface={alert.signal_type === 'surface_outlier'} class:greek={alert.signal_type === 'greek_divergence'}
							title={alert.signal_type === 'surface_outlier' ? 'Surface Outlier: market IV deviates from fitted vol surface' : 'Greek Divergence: delta/vega diverge between market and model'}>
							{alert.signal_type === 'surface_outlier' ? 'Srf' : 'Grk'}
						</span>
					</td>
					<td>
						{#if alert.confidence}
							<span class="conf-badge conf-{alert.confidence}" title={alert.confidence === 'high' ? 'High: large deviation + significant vega' : alert.confidence === 'medium' ? 'Medium: moderate edge' : 'Low: marginal edge'}>{alert.confidence}</span>
						{:else}
							<span class="conf-badge conf-low" title="No confidence level">—</span>
						{/if}
					</td>
					<td class="num">{formatIv(alert.market_iv)}</td>
					<td class="num">{formatIv(alert.model_iv)}</td>
					<td class="num" class:positive={alert.deviation !== null && alert.deviation > 0} class:negative={alert.deviation !== null && alert.deviation < 0}
						title={alert.deviation !== null ? `Market IV is ${alert.deviation > 0 ? 'above' : 'below'} model by ${Math.abs(alert.deviation * 100).toFixed(2)} vol pts` : ''}>
						{formatDeviation(alert.deviation)}
					</td>
					<td class="num spread" class:wide-spread={spread !== null && alert.net_edge !== null && spread > alert.net_edge * 2}
						title={spread !== null ? `Bid: ${formatDollar(alert.bid)} / Ask: ${formatDollar(alert.ask)}` : ''}>
						{spread !== null ? formatDollar(spread) : '—'}
					</td>
					<td class="num edge" title={alert.net_edge !== null ? `$${alert.net_edge.toFixed(2)} profit after spread (= |dev| x 100 x vega - half_spread)` : ''}>{formatDollar(alert.net_edge)}</td>
					<td class="num greek" title={alert.gamma !== null ? `Delta changes by ${alert.gamma.toFixed(6)} per $1 move in underlying` : ''}>
						{formatGreek(alert.gamma, 6)}
					</td>
					<td class="num greek" class:negative={alert.theta !== null && alert.theta < 0}
						title={alert.theta !== null ? `Loses $${Math.abs(alert.theta).toFixed(2)} per day from time decay` : ''}>
						{alert.theta !== null ? formatDollar(alert.theta) : '—'}
					</td>
					<td>
						<button class="dismiss-btn" onclick={() => dismiss(alert.id)} title="Dismiss — marks as reviewed">&#x2715;</button>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>

	{#if $alerts.items.length === 0}
		<p class="empty">No active alerts. Click a Fetch button to scan for mispricings.</p>
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
		font-size: 0.8rem;
	}

	th {
		text-align: left;
		padding: 0.4rem 0.5rem;
		border-bottom: 2px solid #30363d;
		color: #8b949e;
		font-weight: 600;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		white-space: nowrap;
	}

	th.sortable { cursor: pointer; user-select: none; }
	th.sortable:hover { color: #c9d1d9; }

	td {
		padding: 0.35rem 0.5rem;
		border-bottom: 1px solid #21262d;
	}

	tr:hover { background: #161b22; }

	.mono {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.73rem;
	}

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.positive { color: #3fb950; }
	.negative { color: #f85149; }
	.edge { font-weight: 600; color: #f0883e; }

	.dte-urgent { color: #f85149; font-weight: 600; }
	.dte-warn { color: #f0883e; }

	.spread { color: #8b949e; }
	.wide-spread { color: #f85149; }

	.greek { color: #8b949e; font-size: 0.73rem; }

	.badge {
		display: inline-block;
		padding: 0.1rem 0.4rem;
		border-radius: 10px;
		font-size: 0.65rem;
		font-weight: 600;
	}

	.badge.surface {
		background: rgba(56, 139, 253, 0.15);
		color: #58a6ff;
	}

	.badge.greek {
		background: rgba(240, 136, 62, 0.15);
		color: #f0883e;
	}

	.conf-badge {
		font-size: 0.65rem;
		font-weight: 600;
		padding: 0.1rem 0.35rem;
		border-radius: 4px;
	}

	.conf-high { color: #3fb950; background: rgba(63, 185, 80, 0.15); }
	.conf-medium { color: #f0883e; background: rgba(240, 136, 62, 0.15); }
	.conf-low { color: #8b949e; background: rgba(139, 148, 158, 0.15); }

	.dismiss-btn {
		background: none;
		border: 1px solid transparent;
		color: #484f58;
		padding: 0.1rem 0.3rem;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.75rem;
		line-height: 1;
	}

	.dismiss-btn:hover {
		border-color: #f85149;
		color: #f85149;
	}

	.empty {
		text-align: center;
		color: #8b949e;
		padding: 2rem;
	}
</style>
