<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type IvAnalysisData, type SmilePoint } from '$lib/api';
	import { selectedUnderlying } from '$lib/stores';

	let lookbackDays = $state(30);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<IvAnalysisData | null>(null);
	let Plotly: any = $state(null);
	let termChart: HTMLDivElement;
	let skewChart: HTMLDivElement;
	let smileChart: HTMLDivElement;
	let selectedSmileExpiry = $state('');

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
			if (data && data.skew_by_expiry.length > 0 && !selectedSmileExpiry) {
				// Default to 2nd expiry if available (nearest is often too tight)
				selectedSmileExpiry = data.skew_by_expiry.length > 1
					? data.skew_by_expiry[1].expiry
					: data.skew_by_expiry[0].expiry;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load IV analysis';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		const sym = $selectedUnderlying;
		if (sym) load(sym);
	});

	// Render charts when data or Plotly changes
	$effect(() => {
		if (!Plotly || !data) return;
		requestAnimationFrame(() => {
			if (termChart) renderTermAndSkew();
			if (smileChart && selectedSmileExpiry) renderSmile();
		});
	});

	// Re-render smile when expiry selection changes
	$effect(() => {
		if (!Plotly || !data || !smileChart) return;
		const _ = selectedSmileExpiry;
		requestAnimationFrame(() => renderSmile());
	});

	function renderTermAndSkew() {
		if (!data || data.term_structure.length === 0) return;

		const ts = data.term_structure;
		const sk = data.skew_by_expiry;

		// Term structure + skew overlay
		const traces: any[] = [
			{
				type: 'scatter', mode: 'lines+markers',
				x: ts.map(p => p.dte), y: ts.map(p => p.atm_iv),
				name: 'ATM IV', yaxis: 'y',
				line: { color: '#58a6ff', width: 2.5 },
				marker: { size: 7, color: '#58a6ff' },
				hovertemplate: ts.map(p =>
					`${p.expiry} (${p.dte}d)<br>ATM IV: ${(p.atm_iv * 100).toFixed(1)}%<br>Strike: $${p.atm_strike.toLocaleString()}<extra></extra>`
				),
			},
		];

		// Model IV
		const modelPts = ts.filter(p => p.atm_model_iv !== null);
		if (modelPts.length > 0) {
			traces.push({
				type: 'scatter', mode: 'lines',
				x: modelPts.map(p => p.dte), y: modelPts.map(p => p.atm_model_iv),
				name: 'Model IV', yaxis: 'y',
				line: { color: '#3fb950', width: 1.5, dash: 'dot' },
				hovertemplate: modelPts.map(p =>
					`${p.expiry} (${p.dte}d)<br>Model: ${(p.atm_model_iv! * 100).toFixed(1)}%<extra></extra>`
				),
			});
		}

		// 25d put/call IV wings
		const skPut = sk.filter(s => s.put_25d_iv !== null);
		const skCall = sk.filter(s => s.call_25d_iv !== null);
		if (skPut.length > 0) {
			traces.push({
				type: 'scatter', mode: 'lines',
				x: skPut.map(s => s.dte), y: skPut.map(s => s.put_25d_iv),
				name: '25\u0394 Put IV', yaxis: 'y',
				line: { color: '#f85149', width: 1.5, dash: 'dash' },
				hovertemplate: skPut.map(s =>
					`${s.expiry} (${s.dte}d)<br>25\u0394P IV: ${(s.put_25d_iv! * 100).toFixed(1)}%<extra></extra>`
				),
			});
		}
		if (skCall.length > 0) {
			traces.push({
				type: 'scatter', mode: 'lines',
				x: skCall.map(s => s.dte), y: skCall.map(s => s.call_25d_iv),
				name: '25\u0394 Call IV', yaxis: 'y',
				line: { color: '#f0883e', width: 1.5, dash: 'dash' },
				hovertemplate: skCall.map(s =>
					`${s.expiry} (${s.dte}d)<br>25\u0394C IV: ${(s.call_25d_iv! * 100).toFixed(1)}%<extra></extra>`
				),
			});
		}

		// Crush zone marker
		if (ts.length >= 2) {
			let maxDrop = 0, kinkIdx = -1;
			for (let i = 0; i < ts.length - 1; i++) {
				const drop = ts[i].atm_iv - ts[i + 1].atm_iv;
				if (drop > maxDrop) { maxDrop = drop; kinkIdx = i; }
			}
			if (kinkIdx >= 0 && maxDrop > 0.005) {
				traces.push({
					type: 'scatter', mode: 'markers',
					x: [ts[kinkIdx].dte], y: [ts[kinkIdx].atm_iv],
					name: `Crush (-${(maxDrop * 100).toFixed(1)}pts)`,
					marker: { size: 14, color: '#f85149', symbol: 'diamond', line: { width: 2, color: '#f85149' } },
					hovertemplate: `CRUSH<br>${ts[kinkIdx].expiry}<br>IV drop: -${(maxDrop * 100).toFixed(1)}pts<extra></extra>`,
					yaxis: 'y',
				});
			}
		}

		Plotly.newPlot(termChart, traces, {
			title: { text: 'Term Structure & Skew', font: { color: '#e1e4e8', size: 14 } },
			paper_bgcolor: '#0f1117', plot_bgcolor: '#0f1117',
			xaxis: { title: 'Days to Expiry', color: '#8b949e', gridcolor: '#21262d' },
			yaxis: { title: 'Implied Volatility', color: '#8b949e', gridcolor: '#21262d', tickformat: '.0%' },
			font: { color: '#8b949e' },
			margin: { t: 50, b: 50, l: 60, r: 20 },
			legend: { bgcolor: 'rgba(22,27,34,0.8)', font: { color: '#c9d1d9', size: 10 }, orientation: 'h', y: -0.15 },
			hovermode: 'closest',
		}, { responsive: true });

		// Skew chart (risk reversal + butterfly)
		if (skewChart) renderSkewBars();
	}

	function renderSkewBars() {
		if (!data) return;
		const sk = data.skew_by_expiry.filter(s => s.risk_reversal !== null);
		if (sk.length === 0) return;

		const traces: any[] = [
			{
				type: 'bar',
				x: sk.map(s => `${s.dte}d`),
				y: sk.map(s => s.risk_reversal! * 100),
				name: 'Risk Reversal',
				marker: { color: sk.map(s => s.risk_reversal! > 0 ? '#f85149' : '#3fb950') },
				hovertemplate: sk.map(s =>
					`${s.expiry} (${s.dte}d)<br>RR: ${(s.risk_reversal! * 100).toFixed(1)}pts<br>${s.risk_reversal! > 0 ? 'Put skew (downside fear)' : 'Call skew (upside demand)'}<extra></extra>`
				),
			},
		];

		const bfly = sk.filter(s => s.butterfly !== null);
		if (bfly.length > 0) {
			traces.push({
				type: 'scatter', mode: 'lines+markers',
				x: bfly.map(s => `${s.dte}d`),
				y: bfly.map(s => s.butterfly! * 100),
				name: 'Butterfly',
				yaxis: 'y2',
				line: { color: '#bc8cff', width: 2 },
				marker: { size: 5, color: '#bc8cff' },
				hovertemplate: bfly.map(s =>
					`${s.expiry} (${s.dte}d)<br>Bfly: ${(s.butterfly! * 100).toFixed(1)}pts<br>${s.butterfly! > 0 ? 'Fat tails (smile)' : 'Thin tails'}<extra></extra>`
				),
			});
		}

		Plotly.newPlot(skewChart, traces, {
			title: { text: 'Skew by Expiry', font: { color: '#e1e4e8', size: 14 } },
			paper_bgcolor: '#0f1117', plot_bgcolor: '#0f1117',
			xaxis: { color: '#8b949e', gridcolor: '#21262d' },
			yaxis: { title: 'Risk Reversal (pts)', color: '#8b949e', gridcolor: '#21262d', zeroline: true, zerolinecolor: '#30363d' },
			yaxis2: { title: 'Butterfly (pts)', color: '#bc8cff', overlaying: 'y', side: 'right', gridcolor: 'transparent' },
			font: { color: '#8b949e' },
			margin: { t: 50, b: 50, l: 60, r: 60 },
			legend: { bgcolor: 'rgba(22,27,34,0.8)', font: { color: '#c9d1d9', size: 10 }, orientation: 'h', y: -0.15 },
			barmode: 'group',
		}, { responsive: true });
	}

	function renderSmile() {
		if (!data || !selectedSmileExpiry) return;
		const pts = data.smile.filter(p => p.expiry === selectedSmileExpiry);
		if (pts.length === 0) return;

		// Sort by strike for clean lines
		const puts = pts.filter(p => p.option_type === 'P').sort((a, b) => a.strike - b.strike);
		const calls = pts.filter(p => p.option_type === 'C').sort((a, b) => a.strike - b.strike);

		const traces: any[] = [];

		if (puts.length > 0) {
			traces.push({
				type: 'scatter', mode: 'lines+markers',
				x: puts.map(p => p.moneyness), y: puts.map(p => p.market_iv),
				name: 'Put IV', line: { color: '#f85149', width: 2 },
				marker: { size: 5, color: puts.map(p => p.net_edge !== null && p.net_edge > 0 ? '#3fb950' : '#f85149') },
				hovertemplate: puts.map(p =>
					`$${p.strike.toLocaleString()} (${(p.moneyness * 100).toFixed(0)}%)<br>IV: ${(p.market_iv * 100).toFixed(1)}%${p.model_iv ? `<br>Model: ${(p.model_iv * 100).toFixed(1)}%` : ''}${p.deviation ? `<br>Dev: ${(p.deviation * 100).toFixed(1)}pts` : ''}${p.net_edge !== null ? `<br>Edge: $${p.net_edge.toFixed(2)}` : ''}<extra>Put</extra>`
				),
			});
		}
		if (calls.length > 0) {
			traces.push({
				type: 'scatter', mode: 'lines+markers',
				x: calls.map(p => p.moneyness), y: calls.map(p => p.market_iv),
				name: 'Call IV', line: { color: '#58a6ff', width: 2 },
				marker: { size: 5, color: calls.map(p => p.net_edge !== null && p.net_edge > 0 ? '#3fb950' : '#58a6ff') },
				hovertemplate: calls.map(p =>
					`$${p.strike.toLocaleString()} (${(p.moneyness * 100).toFixed(0)}%)<br>IV: ${(p.market_iv * 100).toFixed(1)}%${p.model_iv ? `<br>Model: ${(p.model_iv * 100).toFixed(1)}%` : ''}${p.deviation ? `<br>Dev: ${(p.deviation * 100).toFixed(1)}pts` : ''}${p.net_edge !== null ? `<br>Edge: $${p.net_edge.toFixed(2)}` : ''}<extra>Call</extra>`
				),
			});
		}

		// Model IV line (combined)
		const allSorted = [...pts].sort((a, b) => a.strike - b.strike);
		const withModel = allSorted.filter(p => p.model_iv !== null);
		if (withModel.length > 0) {
			// Deduplicate by strike (use avg model_iv)
			const byStrike = new Map<number, number[]>();
			for (const p of withModel) {
				if (!byStrike.has(p.moneyness)) byStrike.set(p.moneyness, []);
				byStrike.get(p.moneyness)!.push(p.model_iv!);
			}
			const modelX = [...byStrike.keys()].sort((a, b) => a - b);
			const modelY = modelX.map(m => {
				const vals = byStrike.get(m)!;
				return vals.reduce((a, b) => a + b, 0) / vals.length;
			});
			traces.push({
				type: 'scatter', mode: 'lines',
				x: modelX, y: modelY,
				name: 'SVI Model', line: { color: '#3fb950', width: 2, dash: 'dot' },
				hoverinfo: 'skip',
			});
		}

		// ATM line
		traces.push({
			type: 'scatter', mode: 'lines',
			x: [1, 1], y: [0, 5],
			name: 'ATM', line: { color: '#484f58', width: 1, dash: 'dash' },
			hoverinfo: 'skip', showlegend: false,
		});

		const expiryInfo = data.skew_by_expiry.find(s => s.expiry === selectedSmileExpiry);

		Plotly.newPlot(smileChart, traces, {
			title: { text: `Volatility Smile — ${selectedSmileExpiry} (${expiryInfo?.dte ?? '?'}d)`, font: { color: '#e1e4e8', size: 14 } },
			paper_bgcolor: '#0f1117', plot_bgcolor: '#0f1117',
			xaxis: { title: 'Moneyness (Strike / Spot)', color: '#8b949e', gridcolor: '#21262d', tickformat: '.0%' },
			yaxis: { title: 'Implied Volatility', color: '#8b949e', gridcolor: '#21262d', tickformat: '.0%', rangemode: 'tozero' },
			font: { color: '#8b949e' },
			margin: { t: 50, b: 50, l: 60, r: 20 },
			legend: { bgcolor: 'rgba(22,27,34,0.8)', font: { color: '#c9d1d9', size: 10 }, orientation: 'h', y: -0.15 },
			hovermode: 'closest',
		}, { responsive: true });
	}

	function rankColor(rank: number | null): string {
		if (rank === null) return '#8b949e';
		if (rank >= 80) return '#f85149';
		if (rank >= 50) return '#f0883e';
		return '#3fb950';
	}

	function slopeLabel(slope: number | null): string {
		if (slope === null) return '—';
		if (slope > 0.005) return 'Contango';
		if (slope < -0.005) return 'Backwardation';
		return 'Flat';
	}

	function slopeColor(slope: number | null): string {
		if (slope === null) return '#8b949e';
		if (slope > 0.005) return '#3fb950';
		if (slope < -0.005) return '#f85149';
		return '#8b949e';
	}

	function fmtIv(v: number | null): string {
		return v !== null ? (v * 100).toFixed(1) + '%' : '—';
	}

	function fmtPts(v: number | null): string {
		if (v === null) return '—';
		const pts = v * 100;
		return (pts >= 0 ? '+' : '') + pts.toFixed(1);
	}

	let ivRankDisplay = $derived(data?.market_metrics?.iv_rank ?? data?.iv_rank?.rank ?? null);
	let ivPctlDisplay = $derived(data?.market_metrics?.iv_percentile ?? data?.iv_rank?.percentile ?? null);
</script>

<div class="crush-page">
	<header>
		<h1>Volatility Analysis</h1>
		<div class="controls">
			{#if $selectedUnderlying}
				<span class="current-symbol">{$selectedUnderlying}</span>
			{:else}
				<span class="hint">Select a symbol from the navbar</span>
			{/if}
			<select bind:value={lookbackDays} onchange={() => { if ($selectedUnderlying) load($selectedUnderlying); }}>
				<option value={7}>7d</option>
				<option value={14}>14d</option>
				<option value={30}>30d</option>
				<option value={60}>60d</option>
				<option value={90}>90d</option>
			</select>
			{#if loading}
				<span class="loading-indicator">Loading...</span>
			{/if}
		</div>
	</header>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if data && data.term_structure.length > 0}
		<!-- Top metric cards -->
		<div class="cards">
			<div class="card" title="Near-term ATM implied volatility">
				<div class="card-label">ATM IV</div>
				<div class="card-value">{fmtIv(data.term_structure[0].atm_iv)}</div>
				{#if data.term_structure[0].atm_model_iv}
					<div class="card-sub" title="SVI model fair value">
						Model: {fmtIv(data.term_structure[0].atm_model_iv)}
						{#if data.straddles[0]?.vol_premium !== null && data.straddles[0]?.vol_premium !== undefined}
							<span class="vol-premium" class:rich={data.straddles[0].vol_premium! > 0} class:cheap={data.straddles[0].vol_premium! < 0}>
								({fmtPts(data.straddles[0].vol_premium)} vol premium)
							</span>
						{/if}
					</div>
				{/if}
			</div>

			<div class="card" title="Nearest expiry ATM straddle as % of spot — the market's implied expected move">
				<div class="card-label">Implied Move</div>
				<div class="card-value" class:high-move={data.straddles[0]?.straddle_pct > 5}>
					{data.straddles[0] ? data.straddles[0].straddle_pct.toFixed(1) + '%' : '—'}
				</div>
				{#if data.straddles[0]}
					<div class="card-sub">${data.straddles[0].straddle_price.toLocaleString()} straddle</div>
				{/if}
			</div>

			<div class="card" title="Term structure slope: positive = contango (far > near), negative = backwardation (near > far)">
				<div class="card-label">Term Structure</div>
				<div class="card-value" style="color: {slopeColor(data.ts_slope)}">
					{slopeLabel(data.ts_slope)}
				</div>
				{#if data.ts_slope !== null}
					<div class="card-sub">{fmtPts(data.ts_slope)} slope</div>
				{/if}
			</div>

			{#if data.skew_by_expiry.length > 0}
				{@const nearSkew = data.skew_by_expiry[0]}
				<div class="card" title="25-delta risk reversal on nearest expiry: positive = puts more expensive (downside fear)">
					<div class="card-label">Skew (25&Delta;)</div>
					<div class="card-value" style="color: {nearSkew.risk_reversal !== null ? (nearSkew.risk_reversal > 0 ? '#f85149' : '#3fb950') : '#8b949e'}">
						{nearSkew.risk_reversal !== null ? fmtPts(nearSkew.risk_reversal) : '—'}
					</div>
					<div class="card-sub">
						{nearSkew.risk_reversal !== null
							? (nearSkew.risk_reversal > 0 ? 'Put skew' : 'Call skew')
							: ''}
					</div>
				</div>
			{/if}

			<div class="card rank-card" title="IV Rank: where current IV sits relative to its historical range">
				<div class="card-label">IV Rank / Pctl</div>
				{#if ivRankDisplay !== null}
					<div class="card-value" style="color: {rankColor(ivRankDisplay)}">
						{ivRankDisplay.toFixed(0)}%
					</div>
					<div class="rank-bar">
						<div class="rank-fill" style="width: {ivRankDisplay}%; background: {rankColor(ivRankDisplay)}"></div>
					</div>
					<div class="card-sub">
						{ivPctlDisplay !== null ? `Pctl: ${ivPctlDisplay.toFixed(0)}%` : ''}
						{#if data.market_metrics?.iv_index !== null && data.market_metrics?.iv_index !== undefined}
							{ivPctlDisplay !== null ? ' · ' : ''}IV Index: {(data.market_metrics.iv_index * 100).toFixed(1)}%
							{#if data.market_metrics.iv_index_5d_change !== null && data.market_metrics.iv_index_5d_change !== undefined}
								<span class:rich={data.market_metrics.iv_index_5d_change > 0} class:cheap={data.market_metrics.iv_index_5d_change < 0}>
									({data.market_metrics.iv_index_5d_change > 0 ? '+' : ''}{(data.market_metrics.iv_index_5d_change * 100).toFixed(1)} 5d)
								</span>
							{/if}
						{:else if data.iv_rank}
							{ivPctlDisplay !== null ? ' · ' : ''}{fmtIv(data.iv_rank.low)} — {fmtIv(data.iv_rank.high)}
						{/if}
					</div>
				{:else}
					<div class="card-value muted">—</div>
					<div class="card-sub">Fetch to build history</div>
				{/if}
			</div>

			{#if data.market_metrics?.liquidity_rating !== null && data.market_metrics?.liquidity_rating !== undefined}
				<div class="card" title="Tastytrade liquidity rating (1-5 stars, higher = more liquid)">
					<div class="card-label">Liquidity</div>
					<div class="card-value">
						{'★'.repeat(Math.min(data.market_metrics.liquidity_rating, 5))}{'☆'.repeat(Math.max(0, 5 - data.market_metrics.liquidity_rating))}
					</div>
					<div class="card-sub">Rating {data.market_metrics.liquidity_rating}/5</div>
				</div>
			{/if}

			<div class="card" title="Spot price estimate and chain breadth">
				<div class="card-label">Spot / Chain</div>
				<div class="card-value">${data.spot?.toLocaleString() ?? '—'}</div>
				<div class="card-sub">{data.term_structure.length} expiries, {data.smile.length} contracts</div>
			</div>
		</div>

		<!-- Charts row -->
		<div class="charts-row">
			<div class="chart-container">
				<div bind:this={termChart} class="chart" style="height: 340px;"></div>
			</div>
			<div class="chart-container">
				<div bind:this={skewChart} class="chart" style="height: 340px;"></div>
			</div>
		</div>

		<!-- Smile chart with expiry selector -->
		<div class="section">
			<div class="smile-header">
				<h2>Volatility Smile</h2>
				<select bind:value={selectedSmileExpiry}>
					{#each data.skew_by_expiry as s}
						<option value={s.expiry}>{s.expiry} ({s.dte}d) — {s.total_contracts} contracts</option>
					{/each}
				</select>
			</div>
			<div bind:this={smileChart} class="chart" style="height: 340px;"></div>
			<p class="chart-note">Green markers = positive net edge (mispriced). Hover for strike, IV, deviation, and dollar edge.</p>
		</div>

		<!-- Straddle + Skew Table -->
		{#if data.straddles.length > 0}
			<div class="section">
				<h2>ATM Straddle & Skew by Expiry</h2>
				<div class="table-wrapper">
					<table>
						<thead>
							<tr>
								<th>Expiry</th>
								<th class="num" title="Days to expiry">DTE</th>
								<th class="num" title="ATM implied volatility">IV</th>
								<th class="num" title="Market IV minus model IV (vol premium)">Vol Prem</th>
								<th class="num" title="ATM straddle as % of spot">Move%</th>
								<th class="num" title="Straddle price in USD">Straddle</th>
								<th class="num" title="25-delta risk reversal: put IV minus call IV">RR 25&Delta;</th>
								<th class="num" title="Theta per day (positive = you earn)">&#920;/day</th>
								<th class="num" title="Vega exposure per 1% IV move">Vega</th>
								<th class="num" title="Theta earned per dollar of vega risk">&Theta;/V</th>
								<th class="num" title="Combined bid-ask spread cost">Spread</th>
								<th class="num" title="Breakeven range for short straddle">Breakevens</th>
							</tr>
						</thead>
						<tbody>
							{#each data.straddles as s}
								{@const sk = data.skew_by_expiry.find(e => e.expiry === s.expiry)}
								<tr>
									<td class="mono">{s.expiry}</td>
									<td class="num" class:dte-urgent={s.dte <= 3} class:dte-warn={s.dte > 3 && s.dte <= 7}>{s.dte}d</td>
									<td class="num">{fmtIv(s.atm_iv)}</td>
									<td class="num" class:rich={s.vol_premium !== null && s.vol_premium > 0} class:cheap={s.vol_premium !== null && s.vol_premium < 0}>
										{s.vol_premium !== null ? fmtPts(s.vol_premium) : '—'}
									</td>
									<td class="num implied-move" class:high-move={s.straddle_pct > 5}>{s.straddle_pct.toFixed(1)}%</td>
									<td class="num straddle-price">${s.straddle_price.toLocaleString()}</td>
									<td class="num" class:put-skew={s.risk_reversal !== null && s.risk_reversal > 0} class:call-skew={s.risk_reversal !== null && s.risk_reversal < 0}>
										{s.risk_reversal !== null ? fmtPts(s.risk_reversal) : '—'}
									</td>
									<td class="num" class:positive={s.total_theta !== null && s.total_theta < 0}>
										{s.total_theta !== null ? '$' + Math.abs(s.total_theta).toFixed(2) : '—'}
									</td>
									<td class="num">{s.total_vega !== null ? '$' + s.total_vega.toFixed(2) : '—'}</td>
									<td class="num" title="Higher = better theta-to-vega ratio for short vol">
										{s.theta_vega_ratio !== null ? s.theta_vega_ratio.toFixed(2) : '—'}
									</td>
									<td class="num dim">${s.total_spread.toFixed(2)}</td>
									<td class="num breakevens">${s.breakeven_down.toLocaleString()} — ${s.breakeven_up.toLocaleString()}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		<!-- Per-expiry mispricing summary -->
		{#if data.skew_by_expiry.some(s => s.contracts_with_edge > 0)}
			<div class="section">
				<h2>Mispricing by Expiry</h2>
				<div class="table-wrapper">
					<table>
						<thead>
							<tr>
								<th>Expiry</th>
								<th class="num">DTE</th>
								<th class="num" title="Average market-model deviation across all strikes">Avg Dev</th>
								<th class="num" title="Maximum absolute deviation (biggest outlier)">Max Dev</th>
								<th class="num" title="Contracts with positive net edge after spread">Edge Contracts</th>
								<th class="num" title="Total contracts in this expiry">Total</th>
								<th class="num" title="Total absolute vega in this expiry">Total Vega</th>
							</tr>
						</thead>
						<tbody>
							{#each data.skew_by_expiry.filter(s => s.avg_deviation !== null) as s}
								<tr>
									<td class="mono">{s.expiry}</td>
									<td class="num" class:dte-urgent={s.dte <= 3} class:dte-warn={s.dte > 3 && s.dte <= 7}>{s.dte}d</td>
									<td class="num">{fmtPts(s.avg_deviation)}</td>
									<td class="num" class:high-dev={s.max_deviation !== null && s.max_deviation > 0.05}>
										{s.max_deviation !== null ? (s.max_deviation * 100).toFixed(1) + 'pts' : '—'}
									</td>
									<td class="num" class:has-edge={s.contracts_with_edge > 0}>
										{s.contracts_with_edge}
									</td>
									<td class="num dim">{s.total_contracts}</td>
									<td class="num">${s.total_vega.toLocaleString()}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		<!-- Earnings & Dividends -->
		{#if data.earnings.length > 0 || data.dividends.length > 0}
			<div class="section corporate-events">
				<div class="events-row">
					{#if data.earnings.length > 0}
						<div class="event-table">
							<h2>Earnings History</h2>
							<div class="table-wrapper">
								<table>
									<thead>
										<tr>
											<th>Date</th>
											<th class="num">EPS</th>
										</tr>
									</thead>
									<tbody>
										{#each data.earnings.slice(0, 12) as e}
											<tr>
												<td class="mono">{e.date}</td>
												<td class="num" class:positive={e.eps !== null && e.eps > 0} class:negative-eps={e.eps !== null && e.eps < 0}>
													{e.eps !== null ? '$' + e.eps.toFixed(2) : '—'}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						</div>
					{/if}

					{#if data.dividends.length > 0}
						<div class="event-table">
							<h2>Dividend History</h2>
							<div class="table-wrapper">
								<table>
									<thead>
										<tr>
											<th>Date</th>
											<th class="num">Amount</th>
										</tr>
									</thead>
									<tbody>
										{#each data.dividends.slice(0, 12) as d}
											<tr>
												<td class="mono">{d.date}</td>
												<td class="num">{d.amount !== null ? '$' + d.amount.toFixed(4) : '—'}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						</div>
					{/if}
				</div>
			</div>
		{/if}

	{:else if !loading}
		<p class="placeholder">Select a symbol from the navbar to view volatility analysis.</p>
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
	h2 { font-size: 1rem; margin: 0 0 0.75rem 0; color: #c9d1d9; }

	.controls { display: flex; gap: 0.5rem; align-items: center; }

	.current-symbol {
		background: #388bfd26;
		color: #58a6ff;
		padding: 0.35rem 0.75rem;
		border-radius: 6px;
		font-weight: 600;
		font-size: 0.875rem;
	}

	.hint { color: #484f58; font-size: 0.8rem; }
	.loading-indicator { color: #8b949e; font-size: 0.8rem; }

	select {
		background: #21262d;
		color: #c9d1d9;
		border: 1px solid #30363d;
		padding: 0.4rem 0.6rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.8rem;
	}

	/* Cards */
	.cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
		gap: 0.6rem;
		margin-bottom: 1rem;
	}

	.card {
		background: #161b22;
		border: 1px solid #30363d;
		border-radius: 8px;
		padding: 0.75rem;
	}

	.card-label {
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #8b949e;
		margin-bottom: 0.25rem;
	}

	.card-value {
		font-size: 1.35rem;
		font-weight: 700;
		color: #e1e4e8;
		font-variant-numeric: tabular-nums;
	}

	.card-value.muted { color: #484f58; }
	.card-value.high-move { color: #f85149; }

	.card-sub {
		font-size: 0.65rem;
		color: #484f58;
		margin-top: 0.2rem;
	}

	.vol-premium { font-weight: 600; }
	.vol-premium.rich { color: #f85149; }
	.vol-premium.cheap { color: #3fb950; }

	.rank-bar {
		height: 4px;
		background: #21262d;
		border-radius: 2px;
		margin: 0.35rem 0;
		overflow: hidden;
	}

	.rank-fill {
		height: 100%;
		border-radius: 2px;
		transition: width 0.3s;
	}

	/* Charts */
	.charts-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.75rem;
		margin-bottom: 1rem;
	}

	.chart-container {
		background: #161b22;
		border: 1px solid #30363d;
		border-radius: 8px;
		padding: 0.5rem;
	}

	.chart { width: 100%; }

	.section { margin-bottom: 1.25rem; }

	.smile-header {
		display: flex;
		align-items: center;
		gap: 1rem;
		margin-bottom: 0.5rem;
	}

	.smile-header h2 { margin: 0; }

	.chart-note {
		text-align: center;
		font-size: 0.65rem;
		color: #484f58;
		margin-top: 0.25rem;
	}

	/* Tables */
	.table-wrapper { overflow-x: auto; }

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.78rem;
	}

	th {
		text-align: left;
		padding: 0.4rem 0.5rem;
		border-bottom: 2px solid #30363d;
		color: #8b949e;
		font-weight: 600;
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		white-space: nowrap;
	}

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

	.dim { color: #484f58; }
	.straddle-price { font-weight: 600; color: #f0883e; }
	.implied-move { color: #c9d1d9; }
	.implied-move.high-move { color: #f85149; font-weight: 600; }
	.breakevens { font-size: 0.68rem; color: #484f58; white-space: nowrap; }

	.rich { color: #f85149; font-weight: 600; }
	.cheap { color: #3fb950; font-weight: 600; }
	.positive { color: #3fb950; }
	.put-skew { color: #f85149; }
	.call-skew { color: #3fb950; }
	.has-edge { color: #3fb950; font-weight: 600; }
	.high-dev { color: #f0883e; font-weight: 600; }

	.dte-urgent { color: #f85149; font-weight: 600; }
	.dte-warn { color: #f0883e; }

	.negative-eps { color: #f85149; }

	.events-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}

	.event-table {
		background: #161b22;
		border: 1px solid #30363d;
		border-radius: 8px;
		padding: 0.75rem;
	}

	.event-table h2 { margin-bottom: 0.5rem; }

	.error { color: #f85149; }
	.placeholder { color: #8b949e; text-align: center; padding: 3rem; }

	@media (max-width: 900px) {
		.charts-row { grid-template-columns: 1fr; }
		.cards { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
		.events-row { grid-template-columns: 1fr; }
	}
</style>
