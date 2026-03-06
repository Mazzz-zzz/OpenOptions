<script lang="ts">
	import { onMount } from 'svelte';
	import type { SurfaceData } from '$lib/api';

	let { surfaceData }: { surfaceData: SurfaceData } = $props();
	let container3d: HTMLDivElement;
	let container2d: HTMLDivElement;
	let Plotly: any = $state(null);
	let view = $state<'3d' | '2d'>('3d');
	let useMoneyness = $state(true);

	onMount(async () => {
		const mod = await import('plotly.js-dist-min');
		Plotly = mod.default || mod;
	});

	$effect(() => {
		if (!Plotly || !surfaceData || !surfaceData.z_market.length) return;
		// Wait a tick for the container to be in the DOM
		requestAnimationFrame(() => {
			if (view === '3d' && container3d) {
				render3D();
			} else if (view === '2d' && container2d) {
				render2D();
			}
		});
	});

	function render3D() {
		const xAxis = useMoneyness && surfaceData.x_moneyness.length
			? surfaceData.x_moneyness
			: surfaceData.x;
		const xLabel = useMoneyness && surfaceData.x_moneyness.length
			? 'Moneyness (K/S)'
			: 'Strike ($)';

		const traces: any[] = [
			{
				type: 'surface',
				x: xAxis,
				y: surfaceData.y,
				z: surfaceData.z_market,
				colorscale: 'Viridis',
				name: 'Market IV',
				opacity: 0.85,
				connectgaps: true,
				hovertemplate: `${xLabel}: %{x}<br>Expiry: %{y}<br>Market IV: %{z:.2%}<extra>Market IV</extra>`,
			},
			{
				type: 'surface',
				x: xAxis,
				y: surfaceData.y,
				z: surfaceData.z_model,
				colorscale: 'Cividis',
				name: 'Model IV (SVI)',
				opacity: 0.55,
				showscale: false,
				connectgaps: true,
				hovertemplate: `${xLabel}: %{x}<br>Expiry: %{y}<br>Model IV: %{z:.2%}<extra>Model IV</extra>`,
			},
		];

		// Scatter overlay for actual data points
		const pts = surfaceData.points.filter(p => p.market_iv !== null);
		if (pts.length > 0) {
			traces.push({
				type: 'scatter3d',
				mode: 'markers',
				x: pts.map(p => useMoneyness && p.moneyness ? p.moneyness : p.strike),
				y: pts.map(p => p.expiry),
				z: pts.map(p => p.market_iv),
				marker: {
					size: 2.5,
					color: pts.map(p => {
						if (p.deviation === null) return '#8b949e';
						if (Math.abs(p.deviation) > 0.05) return '#f85149';
						if (Math.abs(p.deviation) > 0.02) return '#f0883e';
						return '#3fb950';
					}),
					opacity: 0.9,
				},
				name: 'Data Points',
				hovertemplate: pts.map(p =>
					`${p.symbol}<br>${xLabel}: ${useMoneyness && p.moneyness ? p.moneyness.toFixed(3) : '$' + p.strike.toLocaleString()}<br>` +
					`Market IV: ${p.market_iv ? (p.market_iv * 100).toFixed(1) + '%' : '—'}<br>` +
					`Model IV: ${p.model_iv ? (p.model_iv * 100).toFixed(1) + '%' : '—'}<br>` +
					`Dev: ${p.deviation ? (p.deviation > 0 ? '+' : '') + (p.deviation * 100).toFixed(2) + ' pts' : '—'}<br>` +
					`Edge: ${p.net_edge ? '$' + p.net_edge.toFixed(2) : '—'}` +
					`<extra></extra>`
				),
			});
		}

		const layout = {
			title: {
				text: `Volatility Surface${surfaceData.spot ? ` (Spot: $${surfaceData.spot.toLocaleString()})` : ''}`,
				font: { color: '#e1e4e8', size: 14 },
			},
			paper_bgcolor: '#0f1117',
			plot_bgcolor: '#0f1117',
			scene: {
				xaxis: { title: xLabel, color: '#8b949e', gridcolor: '#21262d' },
				yaxis: { title: 'Expiry', color: '#8b949e', gridcolor: '#21262d' },
				zaxis: { title: 'Implied Volatility', color: '#8b949e', gridcolor: '#21262d', tickformat: '.0%' },
				camera: { eye: { x: 1.8, y: -1.4, z: 0.8 } },
				bgcolor: '#0f1117',
			},
			font: { color: '#8b949e' },
			margin: { t: 50, b: 0, l: 0, r: 0 },
			legend: {
				x: 0, y: 1,
				bgcolor: 'rgba(22,27,34,0.8)',
				font: { color: '#c9d1d9', size: 11 },
			},
		};

		Plotly.newPlot(container3d, traces, layout, { responsive: true });
	}

	function render2D() {
		const traces: any[] = [];
		const colors = [
			'#58a6ff', '#3fb950', '#f0883e', '#f85149', '#bc8cff',
			'#e3b341', '#79c0ff', '#56d364', '#d29922', '#ff7b72',
			'#d2a8ff', '#a5d6ff',
		];

		for (let i = 0; i < surfaceData.y.length; i++) {
			const expiry = surfaceData.y[i];
			const xAxis = useMoneyness && surfaceData.x_moneyness.length
				? surfaceData.x_moneyness
				: surfaceData.x;

			// Market IV line (filter out nulls for clean line)
			const marketPairs: { x: number; y: number }[] = [];
			const modelPairs: { x: number; y: number }[] = [];

			for (let j = 0; j < xAxis.length; j++) {
				const mv = surfaceData.z_market[i][j];
				const miv = surfaceData.z_model[i][j];
				if (mv !== null) marketPairs.push({ x: xAxis[j], y: mv });
				if (miv !== null) modelPairs.push({ x: xAxis[j], y: miv });
			}

			if (marketPairs.length === 0) continue;

			const color = colors[i % colors.length];

			traces.push({
				type: 'scatter',
				mode: 'lines+markers',
				x: marketPairs.map(p => p.x),
				y: marketPairs.map(p => p.y),
				name: `${expiry} Mkt`,
				line: { color, width: 2 },
				marker: { size: 3, color },
				hovertemplate: `${expiry}<br>%{x}<br>Market IV: %{y:.2%}<extra></extra>`,
			});

			traces.push({
				type: 'scatter',
				mode: 'lines',
				x: modelPairs.map(p => p.x),
				y: modelPairs.map(p => p.y),
				name: `${expiry} Model`,
				line: { color, width: 1.5, dash: 'dot' },
				showlegend: false,
				hovertemplate: `${expiry}<br>%{x}<br>Model IV: %{y:.2%}<extra></extra>`,
			});
		}

		const xLabel = useMoneyness && surfaceData.x_moneyness.length
			? 'Moneyness (K/S)'
			: 'Strike ($)';

		const layout = {
			title: {
				text: `IV Smile by Expiry${surfaceData.spot ? ` (Spot: $${surfaceData.spot.toLocaleString()})` : ''}`,
				font: { color: '#e1e4e8', size: 14 },
			},
			paper_bgcolor: '#0f1117',
			plot_bgcolor: '#0f1117',
			xaxis: {
				title: xLabel,
				color: '#8b949e',
				gridcolor: '#21262d',
				zerolinecolor: '#30363d',
			},
			yaxis: {
				title: 'Implied Volatility',
				color: '#8b949e',
				gridcolor: '#21262d',
				zerolinecolor: '#30363d',
				tickformat: '.0%',
			},
			font: { color: '#8b949e' },
			margin: { t: 50, b: 50, l: 60, r: 20 },
			legend: {
				bgcolor: 'rgba(22,27,34,0.8)',
				font: { color: '#c9d1d9', size: 10 },
			},
			hovermode: 'closest',
			// Vertical line at moneyness = 1.0 (ATM)
			shapes: useMoneyness && surfaceData.x_moneyness.length ? [{
				type: 'line',
				x0: 1.0, x1: 1.0,
				y0: 0, y1: 1,
				yref: 'paper',
				line: { color: '#484f58', width: 1, dash: 'dash' },
			}] : [],
			annotations: useMoneyness && surfaceData.x_moneyness.length ? [{
				x: 1.0, y: 1.02, yref: 'paper',
				text: 'ATM', showarrow: false,
				font: { color: '#484f58', size: 10 },
			}] : [],
		};

		Plotly.newPlot(container2d, traces, layout, { responsive: true });
	}
</script>

<div class="surface-controls">
	<div class="view-toggle">
		<button class:active={view === '3d'} onclick={() => view = '3d'} title="3D volatility surface — market IV and model IV as overlapping surfaces">3D Surface</button>
		<button class:active={view === '2d'} onclick={() => view = '2d'} title="2D IV smile — IV curves per expiry, solid = market, dotted = model. Easier to spot deviations.">2D Smile</button>
	</div>
	<label class="moneyness-toggle" title="Toggle between absolute strike price ($) and moneyness (strike / spot). Moneyness normalizes across price levels.">
		<input type="checkbox" bind:checked={useMoneyness} />
		Moneyness axis
	</label>
	{#if surfaceData.spot}
		<span class="spot-label" title="Estimated spot price based on the ATM strike (minimum IV on nearest expiry)">Spot: ${surfaceData.spot.toLocaleString()}</span>
	{/if}
</div>

{#if view === '3d'}
	<div bind:this={container3d} class="surface-chart"></div>
{:else}
	<div bind:this={container2d} class="surface-chart"></div>
{/if}

<div class="legend-note">
	{#if view === '3d'}
		<span title="Red/orange dots indicate large deviations between market and model IV — potential mispricings">
			Dot colors: <span class="dot green"></span> &lt;2% dev <span class="dot orange"></span> 2-5% dev <span class="dot red"></span> &gt;5% dev
		</span>
	{:else}
		<span>Solid lines = Market IV | Dotted lines = Model IV (SVI fit)</span>
	{/if}
</div>

<style>
	.surface-controls {
		display: flex;
		align-items: center;
		gap: 1rem;
		margin-bottom: 0.75rem;
		flex-wrap: wrap;
	}

	.view-toggle {
		display: flex;
		border: 1px solid #30363d;
		border-radius: 6px;
		overflow: hidden;
	}

	.view-toggle button {
		background: #21262d;
		color: #8b949e;
		border: none;
		padding: 0.4rem 0.8rem;
		font-size: 0.8rem;
		cursor: pointer;
		transition: all 0.15s;
	}

	.view-toggle button:first-child {
		border-right: 1px solid #30363d;
	}

	.view-toggle button.active {
		background: #388bfd26;
		color: #58a6ff;
	}

	.view-toggle button:hover:not(.active) {
		color: #c9d1d9;
	}

	.moneyness-toggle {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		color: #8b949e;
		font-size: 0.8rem;
		cursor: pointer;
		user-select: none;
	}

	.moneyness-toggle input {
		accent-color: #58a6ff;
	}

	.spot-label {
		color: #8b949e;
		font-size: 0.8rem;
		margin-left: auto;
		font-variant-numeric: tabular-nums;
	}

	.surface-chart {
		width: 100%;
		height: 550px;
	}

	.legend-note {
		text-align: center;
		color: #484f58;
		font-size: 0.75rem;
		margin-top: 0.5rem;
	}

	.dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin: 0 2px 0 8px;
		vertical-align: middle;
	}

	.dot.green { background: #3fb950; }
	.dot.orange { background: #f0883e; }
	.dot.red { background: #f85149; }
</style>
