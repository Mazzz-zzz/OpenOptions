<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import type { SurfaceData } from '$lib/api';
	import { colors, chartColors, plotlyLayout, plotlyAxis, plotlyLegend } from '$lib/theme';

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

	onDestroy(() => {
		if (Plotly) {
			if (container3d) Plotly.purge(container3d);
			if (container2d) Plotly.purge(container2d);
		}
	});

	$effect(() => {
		if (!Plotly || !surfaceData || !surfaceData.z_market.length) return;
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
						if (p.deviation === null) return colors.textMuted;
						if (Math.abs(p.deviation) > 0.05) return colors.red;
						if (Math.abs(p.deviation) > 0.02) return colors.orange;
						return colors.green;
					}),
					opacity: 0.9,
				},
				name: 'Data Points',
				hovertemplate: pts.map(p =>
					`${p.symbol}<br>${xLabel}: ${useMoneyness && p.moneyness ? p.moneyness.toFixed(3) : '$' + p.strike.toLocaleString()}<br>` +
					`Market IV: ${p.market_iv ? (p.market_iv * 100).toFixed(1) + '%' : '\u2014'}<br>` +
					`Model IV: ${p.model_iv ? (p.model_iv * 100).toFixed(1) + '%' : '\u2014'}<br>` +
					`Dev: ${p.deviation ? (p.deviation > 0 ? '+' : '') + (p.deviation * 100).toFixed(2) + ' pts' : '\u2014'}<br>` +
					`Edge: ${p.net_edge ? '$' + p.net_edge.toFixed(2) : '\u2014'}` +
					`<extra></extra>`
				),
			});
		}

		const layout = plotlyLayout({
			title: {
				text: `Volatility Surface${surfaceData.spot ? ` (Spot: $${surfaceData.spot.toLocaleString()})` : ''}`,
				font: { color: colors.text, size: 14 },
			},
			scene: {
				xaxis: { title: xLabel, color: colors.textSecondary, gridcolor: colors.borderLight },
				yaxis: { title: 'Expiry', color: colors.textSecondary, gridcolor: colors.borderLight },
				zaxis: { title: 'Implied Volatility', color: colors.textSecondary, gridcolor: colors.borderLight, tickformat: '.0%' },
				camera: { eye: { x: 1.8, y: -1.4, z: 0.8 } },
				bgcolor: colors.bg,
			},
			margin: { t: 50, b: 0, l: 0, r: 0 },
			legend: {
				x: 0, y: 1,
				...plotlyLegend,
				font: { ...plotlyLegend.font, size: 11 },
			},
		});

		Plotly.newPlot(container3d, traces, layout, { responsive: true });
	}

	function render2D() {
		const traces: any[] = [];

		for (let i = 0; i < surfaceData.y.length; i++) {
			const expiry = surfaceData.y[i];
			const xAxis = useMoneyness && surfaceData.x_moneyness.length
				? surfaceData.x_moneyness
				: surfaceData.x;

			const marketPairs: { x: number; y: number }[] = [];
			const modelPairs: { x: number; y: number }[] = [];

			for (let j = 0; j < xAxis.length; j++) {
				const mv = surfaceData.z_market[i][j];
				const miv = surfaceData.z_model[i][j];
				if (mv !== null) marketPairs.push({ x: xAxis[j], y: mv });
				if (miv !== null) modelPairs.push({ x: xAxis[j], y: miv });
			}

			if (marketPairs.length === 0) continue;

			const color = chartColors[i % chartColors.length];

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

		const layout = plotlyLayout({
			title: {
				text: `IV Smile by Expiry${surfaceData.spot ? ` (Spot: $${surfaceData.spot.toLocaleString()})` : ''}`,
				font: { color: colors.text, size: 14 },
			},
			xaxis: plotlyAxis(xLabel, { zerolinecolor: colors.border }),
			yaxis: plotlyAxis('Implied Volatility', { zerolinecolor: colors.border, tickformat: '.0%' }),
			legend: plotlyLegend,
			shapes: useMoneyness && surfaceData.x_moneyness.length ? [{
				type: 'line',
				x0: 1.0, x1: 1.0,
				y0: 0, y1: 1,
				yref: 'paper',
				line: { color: colors.textMuted, width: 1, dash: 'dash' },
			}] : [],
			annotations: useMoneyness && surfaceData.x_moneyness.length ? [{
				x: 1.0, y: 1.02, yref: 'paper',
				text: 'ATM', showarrow: false,
				font: { color: colors.textMuted, size: 10 },
			}] : [],
		});

		Plotly.newPlot(container2d, traces, layout, { responsive: true });
	}
</script>

<div class="surface-controls">
	<div class="view-toggle">
		<button class:active={view === '3d'} onclick={() => view = '3d'} title="3D volatility surface">3D Surface</button>
		<button class:active={view === '2d'} onclick={() => view = '2d'} title="2D IV smile curves per expiry">2D Smile</button>
	</div>
	<label class="moneyness-toggle" title="Toggle between absolute strike ($) and moneyness (K/S)">
		<input type="checkbox" bind:checked={useMoneyness} />
		Moneyness axis
	</label>
	{#if surfaceData.spot}
		<span class="spot-label">Spot: ${surfaceData.spot.toLocaleString()}</span>
	{/if}
</div>

{#if view === '3d'}
	<div bind:this={container3d} class="surface-chart"></div>
{:else}
	<div bind:this={container2d} class="surface-chart"></div>
{/if}

<div class="legend-note">
	{#if view === '3d'}
		<span>
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
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}

	.view-toggle button {
		background: var(--bg-input);
		color: var(--text-secondary);
		border: none;
		padding: 0.4rem 0.8rem;
		font-size: 0.8rem;
		cursor: pointer;
		transition: all 0.15s;
	}

	.view-toggle button:first-child {
		border-right: 1px solid var(--border);
	}

	.view-toggle button.active {
		background: var(--badge-blue);
		color: var(--blue);
	}

	.view-toggle button:hover:not(.active) {
		color: var(--text);
	}

	.moneyness-toggle {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		color: var(--text-secondary);
		font-size: 0.8rem;
		cursor: pointer;
		user-select: none;
	}

	.moneyness-toggle input {
		accent-color: var(--blue);
	}

	.spot-label {
		color: var(--text-secondary);
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
		color: var(--text-muted);
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

	.dot.green { background: var(--green); }
	.dot.orange { background: var(--orange); }
	.dot.red { background: var(--red); }
</style>
