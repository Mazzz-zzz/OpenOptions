<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import type { MlEpochMetric } from '$lib/api';
	import { colors, plotlyLayout, plotlyAxis, plotlyLegend } from '$lib/theme';

	let { metrics }: { metrics: MlEpochMetric[] } = $props();
	let Plotly: any = $state(null);
	let chartEl: HTMLDivElement;

	onMount(async () => {
		const mod = await import('plotly.js-dist-min');
		Plotly = mod.default || mod;
	});

	onDestroy(() => {
		if (Plotly && chartEl) Plotly.purge(chartEl);
	});

	$effect(() => {
		if (!Plotly || !chartEl || metrics.length === 0) return;
		const epochs = metrics.map((m) => m.epoch);
		const traces: any[] = [];

		const trainPts = metrics.filter((m) => m.train_loss !== null);
		if (trainPts.length > 0) {
			traces.push({
				type: 'scatter',
				mode: 'lines',
				x: trainPts.map((m) => m.epoch),
				y: trainPts.map((m) => m.train_loss),
				name: 'Train Loss',
				line: { color: colors.blue, width: 2 }
			});
		}

		const valPts = metrics.filter((m) => m.val_loss !== null);
		if (valPts.length > 0) {
			traces.push({
				type: 'scatter',
				mode: 'lines',
				x: valPts.map((m) => m.epoch),
				y: valPts.map((m) => m.val_loss),
				name: 'Val Loss',
				line: { color: colors.red, width: 2 }
			});
		}

		Plotly.newPlot(
			chartEl,
			traces,
			plotlyLayout({
				title: { text: 'Loss Curve', font: { color: colors.text, size: 14 } },
				xaxis: plotlyAxis('Epoch'),
				yaxis: plotlyAxis('Loss'),
				legend: { ...plotlyLegend, orientation: 'h', y: -0.15 },
				margin: { t: 50, b: 50, l: 60, r: 20 }
			}),
			{ responsive: true }
		);
	});
</script>

<div class="chart-container">
	{#if metrics.length === 0}
		<p class="empty">No epoch metrics to display</p>
	{:else}
		<div bind:this={chartEl} class="chart" style="height: 300px;"></div>
	{/if}
</div>

<style>
	.chart-container {
		background: var(--bg-card);
		border: 1px solid var(--border-light);
		border-radius: 8px;
		padding: 0.5rem;
		box-shadow: var(--shadow-sm);
	}

	.chart {
		width: 100%;
	}

	.empty {
		color: var(--text-muted);
		text-align: center;
		padding: 2rem;
		font-size: 0.8rem;
	}
</style>
