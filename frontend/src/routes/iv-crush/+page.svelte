<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type IvAnalysisData } from '$lib/api';
	import { selectedUnderlying } from '$lib/stores';

	let lookbackDays = $state(30);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<IvAnalysisData | null>(null);
	let Plotly: any = $state(null);
	let termChart: HTMLDivElement;
	let histChart: HTMLDivElement;

	onMount(async () => {
		const mod = await import('plotly.js-dist-min');
		Plotly = mod.default || mod;
	});

	async function load(underlying: string) {
		if (!underlying) return;
		loading = true;
		error = null;
		try {
			data = await api.getIvAnalysis(underlying, lookbackDays);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load IV analysis';
		} finally {
			loading = false;
		}
	}

	// React to global symbol changes
	$effect(() => {
		const sym = $selectedUnderlying;
		if (sym) load(sym);
	});

	$effect(() => {
		if (!Plotly || !data) return;
		requestAnimationFrame(() => {
			if (termChart) renderTermStructure();
			if (histChart && data!.historical_iv.length > 0) renderHistorical();
		});
	});

	function renderTermStructure() {
		if (!data || data.term_structure.length === 0) return;

		const ts = data.term_structure;
		const traces: any[] = [
			{
				type: 'scatter',
				mode: 'lines+markers',
				x: ts.map(p => p.dte),
				y: ts.map(p => p.atm_iv),
				name: 'Market ATM IV',
				line: { color: '#58a6ff', width: 2.5 },
				marker: { size: 7, color: '#58a6ff' },
				hovertemplate: ts.map(p =>
					`${p.expiry} (${p.dte}d)<br>ATM IV: ${(p.atm_iv * 100).toFixed(1)}%<br>Strike: $${p.atm_strike.toLocaleString()}<extra></extra>`
				),
			},
		];

		const modelPts = ts.filter(p => p.atm_model_iv !== null);
		if (modelPts.length > 0) {
			traces.push({
				type: 'scatter',
				mode: 'lines',
				x: modelPts.map(p => p.dte),
				y: modelPts.map(p => p.atm_model_iv),
				name: 'Model ATM IV',
				line: { color: '#3fb950', width: 1.5, dash: 'dot' },
				hovertemplate: modelPts.map(p =>
					`${p.expiry} (${p.dte}d)<br>Model IV: ${(p.atm_model_iv! * 100).toFixed(1)}%<extra></extra>`
				),
			});
		}

		if (ts.length >= 2) {
			let maxDrop = 0;
			let kinkIdx = -1;
			for (let i = 0; i < ts.length - 1; i++) {
				const drop = ts[i].atm_iv - ts[i + 1].atm_iv;
				if (drop > maxDrop) {
					maxDrop = drop;
					kinkIdx = i;
				}
			}
			if (kinkIdx >= 0 && maxDrop > 0.01) {
				traces.push({
					type: 'scatter',
					mode: 'markers',
					x: [ts[kinkIdx].dte],
					y: [ts[kinkIdx].atm_iv],
					name: `Crush zone (-${(maxDrop * 100).toFixed(1)} pts)`,
					marker: { size: 14, color: '#f85149', symbol: 'diamond', line: { width: 2, color: '#f85149' } },
					hovertemplate: `CRUSH ZONE<br>${ts[kinkIdx].expiry} (${ts[kinkIdx].dte}d)<br>IV: ${(ts[kinkIdx].atm_iv * 100).toFixed(1)}%<br>Drop to next: -${(maxDrop * 100).toFixed(1)} pts<extra></extra>`,
				});
			}
		}

		Plotly.newPlot(termChart, traces, {
			title: { text: 'IV Term Structure (ATM)', font: { color: '#e1e4e8', size: 14 } },
			paper_bgcolor: '#0f1117',
			plot_bgcolor: '#0f1117',
			xaxis: { title: 'Days to Expiry', color: '#8b949e', gridcolor: '#21262d' },
			yaxis: { title: 'Implied Volatility', color: '#8b949e', gridcolor: '#21262d', tickformat: '.0%' },
			font: { color: '#8b949e' },
			margin: { t: 50, b: 50, l: 60, r: 20 },
			legend: { bgcolor: 'rgba(22,27,34,0.8)', font: { color: '#c9d1d9', size: 11 } },
			hovermode: 'closest',
		}, { responsive: true });
	}

	function renderHistorical() {
		if (!data || data.historical_iv.length === 0) return;

		const hist = data.historical_iv;
		const currentIv = data.iv_rank?.current_iv;

		const traces: any[] = [{
			type: 'scatter',
			mode: 'lines',
			x: hist.map(h => h.ts),
			y: hist.map(h => h.iv),
			name: 'ATM IV',
			line: { color: '#58a6ff', width: 1.5 },
			fill: 'tozeroy',
			fillcolor: 'rgba(88,166,255,0.08)',
			hovertemplate: '%{x}<br>IV: %{y:.2%}<extra></extra>',
		}];

		if (currentIv !== null && currentIv !== undefined) {
			traces.push({
				type: 'scatter',
				mode: 'lines',
				x: [hist[0].ts, hist[hist.length - 1].ts],
				y: [currentIv, currentIv],
				name: `Current: ${(currentIv * 100).toFixed(1)}%`,
				line: { color: '#f0883e', width: 1.5, dash: 'dash' },
				hoverinfo: 'skip',
			});
		}

		Plotly.newPlot(histChart, traces, {
			title: { text: `Historical ATM IV (${lookbackDays}d)`, font: { color: '#e1e4e8', size: 14 } },
			paper_bgcolor: '#0f1117',
			plot_bgcolor: '#0f1117',
			xaxis: { color: '#8b949e', gridcolor: '#21262d' },
			yaxis: { title: 'Implied Volatility', color: '#8b949e', gridcolor: '#21262d', tickformat: '.0%' },
			font: { color: '#8b949e' },
			margin: { t: 50, b: 50, l: 60, r: 20 },
			legend: { bgcolor: 'rgba(22,27,34,0.8)', font: { color: '#c9d1d9', size: 11 } },
			hovermode: 'x unified',
		}, { responsive: true });
	}

	function rankColor(rank: number | null): string {
		if (rank === null) return '#8b949e';
		if (rank >= 80) return '#f85149';
		if (rank >= 50) return '#f0883e';
		return '#3fb950';
	}

	function crushVerdict(rank: number | null): string {
		if (rank === null) return 'No data';
		if (rank >= 80) return 'HIGH IV — Prime crush candidate';
		if (rank >= 60) return 'ELEVATED IV — Moderate crush opportunity';
		if (rank >= 40) return 'NEUTRAL IV — Limited crush edge';
		return 'LOW IV — Avoid selling vol';
	}
</script>

<div class="crush-page">
	<header>
		<h1 title="IV crush strategies profit when implied volatility drops — typically after events, earnings, or when term structure normalizes">IV Crush Analysis</h1>
		<div class="controls">
			{#if $selectedUnderlying}
				<span class="current-symbol">{$selectedUnderlying}</span>
			{:else}
				<span class="hint">Fetch a symbol from the navbar</span>
			{/if}
			<select bind:value={lookbackDays} onchange={() => { if ($selectedUnderlying) load($selectedUnderlying); }} title="Historical lookback period for IV rank calculation">
				<option value={7}>7d lookback</option>
				<option value={14}>14d lookback</option>
				<option value={30}>30d lookback</option>
				<option value={60}>60d lookback</option>
				<option value={90}>90d lookback</option>
			</select>
			{#if loading}
				<span class="loading">Loading...</span>
			{/if}
		</div>
	</header>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if data}
		<!-- IV Rank Card -->
		<div class="cards">
			<div class="card rank-card" title="IV Rank = where current IV sits within its recent range. 100 = at the high, 0 = at the low.">
				<div class="card-label">IV Rank ({data.iv_rank?.lookback_days ?? lookbackDays}d)</div>
				{#if data.iv_rank && data.iv_rank.rank !== null}
					<div class="rank-value" style="color: {rankColor(data.iv_rank.rank)}">
						{data.iv_rank.rank.toFixed(0)}%
					</div>
					<div class="rank-bar">
						<div class="rank-fill" style="width: {data.iv_rank.rank}%; background: {rankColor(data.iv_rank.rank)}"></div>
						<div class="rank-marker" style="left: {data.iv_rank.rank}%"></div>
					</div>
					<div class="rank-labels">
						<span title="Lowest ATM IV in the lookback period">Lo: {(data.iv_rank.low! * 100).toFixed(1)}%</span>
						<span title="Current near-term ATM implied volatility">Now: {(data.iv_rank.current_iv! * 100).toFixed(1)}%</span>
						<span title="Highest ATM IV in the lookback period">Hi: {(data.iv_rank.high! * 100).toFixed(1)}%</span>
					</div>
					<div class="verdict" style="color: {rankColor(data.iv_rank.rank)}">{crushVerdict(data.iv_rank.rank)}</div>
				{:else}
					<div class="rank-value muted">—</div>
					<div class="verdict muted">Need more historical data (fetch multiple times)</div>
				{/if}
			</div>

			<div class="card" title="IV Percentile = % of historical observations below current IV">
				<div class="card-label">IV Percentile</div>
				<div class="card-value" style="color: {rankColor(data.iv_rank?.percentile ?? null)}">
					{data.iv_rank?.percentile !== null && data.iv_rank?.percentile !== undefined ? data.iv_rank.percentile.toFixed(0) + '%' : '—'}
				</div>
				<div class="card-sub">{data.iv_rank?.data_points ?? 0} observations</div>
			</div>

			<div class="card" title="Estimated spot price (ATM strike on nearest expiry)">
				<div class="card-label">Spot Price</div>
				<div class="card-value">${data.spot?.toLocaleString() ?? '—'}</div>
			</div>

			<div class="card" title="Number of expiries with ATM IV data">
				<div class="card-label">Expiries</div>
				<div class="card-value">{data.term_structure.length}</div>
			</div>
		</div>

		<!-- Term Structure Chart -->
		<div class="section">
			<div bind:this={termChart} class="chart" style="height: 350px;"></div>
			<p class="chart-note" title="A steep drop between adjacent expiries indicates where the market expects volatility to collapse (the 'crush')">
				Red diamond = steepest IV drop between expiries (crush zone). Dotted green = SVI model IV.
			</p>
		</div>

		<!-- Historical IV Chart -->
		{#if data.historical_iv.length > 0}
			<div class="section">
				<div bind:this={histChart} class="chart" style="height: 280px;"></div>
			</div>
		{/if}

		<!-- ATM Straddle Table -->
		{#if data.straddles.length > 0}
			<div class="section">
				<h2 title="ATM straddle = buy (or sell) a call + put at the same strike. The price reflects expected move. Selling the straddle profits from crush.">ATM Straddle Monitor</h2>
				<div class="table-wrapper">
					<table>
						<thead>
							<tr>
								<th title="Option expiration date">Expiry</th>
								<th class="num" title="Calendar days until expiry">DTE</th>
								<th class="num" title="ATM strike price used for this straddle">Strike</th>
								<th class="num" title="ATM implied volatility — higher = more expensive straddle">IV</th>
								<th class="num" title="ATM call mid price in USD">Call</th>
								<th class="num" title="ATM put mid price in USD">Put</th>
								<th class="num" title="Straddle price = call + put. This is the premium collected when selling.">Straddle ($)</th>
								<th class="num" title="Straddle as % of spot — the implied expected move. E.g. 5% means market expects a 5% move by expiry.">Implied Move</th>
								<th class="num" title="Breakeven prices — underlying must stay within this range for short straddle to profit">Breakevens</th>
								<th class="num" title="Combined bid-ask spread of call + put — the cost of entering/exiting">Spread</th>
								<th class="num" title="Combined theta — daily time decay in USD. Positive for short straddle (you collect this daily).">Theta/day</th>
								<th class="num" title="Combined vega — dollar P&L per 1% IV change. Negative for short straddle (you profit from IV dropping).">Vega</th>
							</tr>
						</thead>
						<tbody>
							{#each data.straddles as s}
								<tr>
									<td>{s.expiry}</td>
									<td class="num" class:dte-urgent={s.dte <= 3} class:dte-warn={s.dte > 3 && s.dte <= 7}>{s.dte}d</td>
									<td class="num">${s.atm_strike.toLocaleString()}</td>
									<td class="num">{(s.atm_iv * 100).toFixed(1)}%</td>
									<td class="num">${s.call_mid.toLocaleString()}</td>
									<td class="num">${s.put_mid.toLocaleString()}</td>
									<td class="num straddle-price">${s.straddle_price.toLocaleString()}</td>
									<td class="num implied-move" class:high-move={s.straddle_pct > 5}>{s.straddle_pct.toFixed(1)}%</td>
									<td class="num breakevens">${s.breakeven_down.toLocaleString()} — ${s.breakeven_up.toLocaleString()}</td>
									<td class="num spread">${s.total_spread.toFixed(2)}</td>
									<td class="num" class:positive={s.total_theta !== null && s.total_theta < 0}>
										{s.total_theta !== null ? '$' + Math.abs(s.total_theta).toFixed(2) : '—'}
									</td>
									<td class="num">{s.total_vega !== null ? '$' + s.total_vega.toFixed(2) : '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				<p class="chart-note">
					Short straddle strategy: sell the straddle, collect the premium, profit if underlying stays within breakevens.
					Theta works in your favor (positive decay). Vega is your risk (if IV rises, you lose).
				</p>
			</div>
		{/if}
	{:else if !loading}
		<p class="placeholder">Fetch a symbol from the navbar to view IV crush opportunities.</p>
	{/if}
</div>

<style>
	.crush-page header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1rem;
	}

	h1 { font-size: 1.5rem; margin: 0; }
	h2 { font-size: 1.1rem; margin: 0 0 0.75rem 0; color: #c9d1d9; }

	.controls { display: flex; gap: 0.5rem; align-items: center; }

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

	select {
		background: #21262d;
		color: #c9d1d9;
		border: 1px solid #30363d;
		padding: 0.5rem 1rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.875rem;
	}

	.cards {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr 1fr;
		gap: 0.75rem;
		margin-bottom: 1.25rem;
	}

	.card {
		background: #161b22;
		border: 1px solid #30363d;
		border-radius: 8px;
		padding: 1rem;
	}

	.card-label {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #8b949e;
		margin-bottom: 0.35rem;
	}

	.card-value {
		font-size: 1.5rem;
		font-weight: 700;
		color: #e1e4e8;
		font-variant-numeric: tabular-nums;
	}

	.card-sub {
		font-size: 0.7rem;
		color: #484f58;
		margin-top: 0.25rem;
	}

	.rank-card { grid-row: span 1; }

	.rank-value {
		font-size: 2rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}

	.rank-value.muted { color: #484f58; }

	.rank-bar {
		position: relative;
		height: 8px;
		background: #21262d;
		border-radius: 4px;
		margin: 0.5rem 0;
		overflow: visible;
	}

	.rank-fill {
		height: 100%;
		border-radius: 4px;
		transition: width 0.3s;
	}

	.rank-marker {
		position: absolute;
		top: -3px;
		width: 3px;
		height: 14px;
		background: #e1e4e8;
		border-radius: 2px;
		transform: translateX(-50%);
	}

	.rank-labels {
		display: flex;
		justify-content: space-between;
		font-size: 0.7rem;
		color: #8b949e;
	}

	.verdict {
		font-size: 0.75rem;
		font-weight: 600;
		margin-top: 0.5rem;
	}

	.verdict.muted { color: #484f58; }

	.section { margin-bottom: 1.5rem; }

	.chart { width: 100%; }

	.chart-note {
		text-align: center;
		font-size: 0.7rem;
		color: #484f58;
		margin-top: 0.35rem;
	}

	.table-wrapper { overflow-x: auto; }

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.8rem;
	}

	th {
		text-align: left;
		padding: 0.4rem 0.6rem;
		border-bottom: 2px solid #30363d;
		color: #8b949e;
		font-weight: 600;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		white-space: nowrap;
	}

	td {
		padding: 0.4rem 0.6rem;
		border-bottom: 1px solid #21262d;
	}

	tr:hover { background: #161b22; }

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.straddle-price { font-weight: 600; color: #f0883e; }
	.implied-move { color: #c9d1d9; }
	.implied-move.high-move { color: #f85149; font-weight: 600; }
	.breakevens { font-size: 0.73rem; color: #8b949e; white-space: nowrap; }
	.spread { color: #8b949e; }
	.positive { color: #3fb950; }

	.dte-urgent { color: #f85149; font-weight: 600; }
	.dte-warn { color: #f0883e; }

	.error { color: #f85149; }
	.placeholder { color: #8b949e; text-align: center; padding: 3rem; }

	@media (max-width: 768px) {
		.cards { grid-template-columns: 1fr 1fr; }
	}
</style>
