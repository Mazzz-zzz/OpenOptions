<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		api,
		type MlRunData,
		type MlEpochMetric,
		type MlExperimentData,
		type TrainRequest
	} from '$lib/api';
	import { addToast } from '$lib/stores';
	import {
		mlOverview,
		loadMlOverview,
		mlExperiments,
		mlModels,
		loadMlModels,
		mlRounds,
		loadMlRounds,
		triggerTraining,
		startPolling,
		stopPolling,
		setMetricsRefreshCallback
	} from '$lib/ml-stores';
	import MetricCard from '$lib/components/ml/MetricCard.svelte';
	import LossChart from '$lib/components/ml/LossChart.svelte';
	import ModelComparisonChart from '$lib/components/ml/ModelComparisonChart.svelte';
	import TrainingProgress from '$lib/components/ml/TrainingProgress.svelte';

	let activeTab = $state<'overview' | 'deploy' | 'exogenous' | 'experiments' | 'models' | 'rounds'>('overview');
	let loading = $state(false);
	let error = $state<string | null>(null);

	// Experiments tab state
	let expandedExp = $state<number | null>(null);
	let expRuns = $state<MlRunData[]>([]);
	let expRunsLoading = $state(false);

	// Overview tab state
	let selectedRunId = $state<number | null>(null);
	let epochMetrics = $state<MlEpochMetric[]>([]);
	let metricsLoading = $state(false);
	let metricsError = $state<string | null>(null);

	// Deploy tab state
	let deployExpName = $state('');
	let deployDescription = $state('');
	let deployDataVersion = $state('v2.1');
	let deployInstanceType = $state('ml.m5.xlarge');
	let deployModelType = $state<'lgbm' | 'catboost'>('lgbm');
	let deployUpload = $state(false);
	let deployMultiTarget = $state(true);
	let deployMaxTrainEras = $state(400);
	let deployNeutralizationPct = $state(50);
	let deployNeutralizerAware = $state(true);
	let deploySampleWeightAware = $state(true);
	let deployExogenousData = $state(false);
	let exogenousSymbols = $state('SPY,QQQ,IWM,XLK,XLF,XLE,XLV,AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,JPM');
	// LightGBM params
	let lgbmNumLeaves = $state(512);
	let lgbmMaxDepth = $state(8);
	let lgbmLearningRate = $state(0.005);
	let lgbmNumRounds = $state(10000);
	let lgbmFeatureFraction = $state(0.1);
	let lgbmBaggingFraction = $state(0.5);
	let lgbmEarlyStopping = $state(200);
	let deployLoading = $state(false);

	// Estimated cost
	const instanceRates: Record<string, { rate: number; spec: string }> = {
		'ml.m5.large': { rate: 0.134, spec: '2 vCPU, 8 GB' },
		'ml.m5.xlarge': { rate: 0.269, spec: '4 vCPU, 16 GB' },
		'ml.m5.2xlarge': { rate: 0.538, spec: '8 vCPU, 32 GB' },
		'ml.m5.4xlarge': { rate: 1.075, spec: '16 vCPU, 64 GB' },
		'ml.m5.12xlarge': { rate: 3.226, spec: '48 vCPU, 192 GB' },
		'ml.c5.xlarge': { rate: 0.235, spec: '4 vCPU, 8 GB' },
		'ml.c5.2xlarge': { rate: 0.470, spec: '8 vCPU, 16 GB' },
	};
	let estimatedCost = $derived.by(() => {
		const info = instanceRates[deployInstanceType];
		if (!info) return null;
		const minutes = 45; // Signals data is a fixed size
		return {
			low: (info.rate * minutes / 60).toFixed(2),
			high: (info.rate * minutes * 1.5 / 60).toFixed(2),
			minutes
		};
	});

	// Exogenous data sources
	interface ExoSource {
		id: string;
		name: string;
		status: 'active' | 'planned' | 'disabled';
		provider: string;
		symbols: number;
		universe: number;
		historyDays: number;
		features: ExoFeature[];
	}
	interface ExoFeature {
		name: string;
		source: string;
		desc: string;
		coverage: number;
		signal: 'high' | 'medium' | 'low' | 'unknown';
		usedInRuns: number;
	}

	const exoSources: ExoSource[] = [
		{
			id: 'tastytrade',
			name: 'Tastytrade Options',
			status: 'active',
			provider: 'Tastytrade REST API',
			symbols: exogenousSymbols.split(',').filter(Boolean).length,
			universe: 5000,
			historyDays: 0,
			features: [
				{ name: 'opt_iv_rank', source: 'tastytrade', desc: 'IV rank (0-100) — where current IV sits vs 52-week range', coverage: 9.7, signal: 'medium', usedInRuns: 0 },
				{ name: 'opt_iv_percentile', source: 'tastytrade', desc: 'IV percentile (0-100) — % of days IV was lower', coverage: 9.7, signal: 'medium', usedInRuns: 0 },
				{ name: 'opt_iv_index', source: 'tastytrade', desc: 'Current IV index level (decimal)', coverage: 9.7, signal: 'low', usedInRuns: 0 },
				{ name: 'opt_iv_5d_chg', source: 'tastytrade', desc: 'IV index 5-day change — vol momentum', coverage: 9.7, signal: 'high', usedInRuns: 0 },
				{ name: 'opt_skew_25d', source: 'tastytrade', desc: '25-delta risk reversal (put IV - call IV) — downside fear', coverage: 8.1, signal: 'high', usedInRuns: 0 },
				{ name: 'opt_term_slope', source: 'tastytrade', desc: 'Near vs far expiry IV slope — event risk signal', coverage: 8.1, signal: 'medium', usedInRuns: 0 },
			],
		},
	];

	const coverageBySector = [
		{ sector: 'Technology', pct: 82 },
		{ sector: 'Financials', pct: 58 },
		{ sector: 'Healthcare', pct: 37 },
		{ sector: 'Energy', pct: 31 },
		{ sector: 'Consumer Disc.', pct: 45 },
		{ sector: 'Industrials', pct: 28 },
		{ sector: 'Comm. Services', pct: 52 },
		{ sector: 'Utilities', pct: 12 },
	];

	const coverageByMcap = [
		{ tier: 'Mega (>200B)', pct: 94 },
		{ tier: 'Large (10-200B)', pct: 68 },
		{ tier: 'Mid (2-10B)', pct: 35 },
		{ tier: 'Small (300M-2B)', pct: 8 },
		{ tier: 'Micro (<300M)', pct: 1 },
	];

	let expandedSource = $state<string | null>(null);
	let symbolSearch = $state('');

	// Parsed symbol list for the symbol table
	let parsedSymbols = $derived(
		exogenousSymbols.split(',').map(s => s.trim()).filter(Boolean)
	);

	let filteredSymbols = $derived(
		symbolSearch
			? parsedSymbols.filter(s => s.toLowerCase().includes(symbolSearch.toLowerCase()))
			: parsedSymbols
	);

	// All features across all sources
	let allFeatures = $derived(exoSources.flatMap(s => s.features));

	function signalColor(signal: string): string {
		switch (signal) {
			case 'high': return 'var(--green)';
			case 'medium': return 'var(--orange)';
			case 'low': return 'var(--text-muted)';
			default: return 'var(--text-muted)';
		}
	}

	async function handleDeploy() {
		if (!deployExpName.trim()) return;
		deployLoading = true;
		try {
			const config: TrainRequest = {
				experiment_name: deployExpName.trim(),
				feature_set: 'signals_' + deployDataVersion,
				model_type: deployModelType,
				instance_type: deployInstanceType,
				upload: deployUpload,
				neutralization_pct: deployNeutralizationPct,
				hyperparams: {
					...(deployModelType === 'lgbm' ? {
						num_leaves: lgbmNumLeaves,
						feature_fraction: lgbmFeatureFraction,
						bagging_fraction: lgbmBaggingFraction,
					} : {}),
					max_depth: lgbmMaxDepth,
					learning_rate: lgbmLearningRate,
					num_rounds: lgbmNumRounds,
					early_stopping_rounds: lgbmEarlyStopping,
					multi_target_enabled: deployMultiTarget,
					max_train_eras: deployMaxTrainEras,
					neutralizer_aware: deployNeutralizerAware,
					sample_weight_aware: deploySampleWeightAware,
					data_version: deployDataVersion,
					tournament: 'signals',
					exogenous_data: deployExogenousData,
					...(deployExogenousData ? { exogenous_symbols: exogenousSymbols.split(',').map(s => s.trim()).filter(Boolean).join(',') } : {}),
				},
			};
			if (deployDescription.trim()) {
				config.description = deployDescription.trim();
			}
			const result = await triggerTraining(config, 'signals');
			addToast(`Signals training started: Run #${result.run_id}`, 'success');
			activeTab = 'overview';
			await loadMlOverview('signals');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to start training', 'error');
		} finally {
			deployLoading = false;
		}
	}

	async function refreshSelectedMetrics() {
		if (selectedRunId === null) return;
		try {
			const res = await api.getMlRunMetrics(selectedRunId);
			epochMetrics = res.data;
		} catch {
			// Silent
		}
	}

	onMount(async () => {
		loading = true;
		setMetricsRefreshCallback(refreshSelectedMetrics);
		try {
			await Promise.all([
				loadMlOverview('signals'),
				mlExperiments.refresh('signals'),
				loadMlModels('signals'),
				loadMlRounds('signals')
			]);
			if (($mlOverview?.active_runs ?? 0) > 0) {
				startPolling('signals');
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load Signals data';
			addToast(error!, 'error');
		} finally {
			loading = false;
		}
	});

	onDestroy(() => {
		setMetricsRefreshCallback(null);
		stopPolling();
	});

	async function handleCancelRun(runId: number) {
		try {
			await api.cancelTraining(runId);
			addToast(`Run #${runId} cancelled`, 'success');
			await loadMlOverview('signals');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to cancel run', 'error');
		}
	}

	async function toggleExperiment(exp: MlExperimentData) {
		if (expandedExp === exp.id) {
			expandedExp = null;
			expRuns = [];
			return;
		}
		expandedExp = exp.id;
		expRunsLoading = true;
		try {
			const res = await api.getMlRuns(exp.id);
			expRuns = res.data;
		} catch {
			expRuns = [];
		} finally {
			expRunsLoading = false;
		}
	}

	async function loadRunMetrics(runId: number) {
		selectedRunId = runId;
		metricsLoading = true;
		metricsError = null;
		epochMetrics = [];
		try {
			const res = await api.getMlRunMetrics(runId);
			epochMetrics = res.data;
		} catch (e) {
			metricsError = e instanceof Error ? e.message : `Failed to load metrics for run #${runId}`;
			addToast(metricsError, 'error');
		} finally {
			metricsLoading = false;
		}
	}

	async function promoteModel(modelId: number, stage: string) {
		try {
			await api.updateMlModel(modelId, { stage });
			await loadMlModels('signals');
			addToast(`Model promoted to ${stage}`, 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to promote model', 'error');
		}
	}

	function statusColor(status: string): string {
		switch (status) {
			case 'completed':
			case 'resolved':
				return 'var(--green)';
			case 'running':
			case 'pending':
				return 'var(--blue)';
			case 'failed':
				return 'var(--red)';
			default:
				return 'var(--text-muted)';
		}
	}

	function stageColor(stage: string): string {
		switch (stage) {
			case 'prod':
				return 'var(--green)';
			case 'staging':
				return 'var(--orange)';
			default:
				return 'var(--text-muted)';
		}
	}

	function stageBadgeBg(stage: string): string {
		switch (stage) {
			case 'prod':
				return 'var(--badge-green)';
			case 'staging':
				return 'var(--badge-orange)';
			default:
				return 'var(--badge-muted)';
		}
	}

	function fmt(v: number | null, decimals = 4): string {
		if (v === null) return '\u2014';
		return v.toFixed(decimals);
	}
</script>

<div class="ml-page">
	<header>
		<div>
			<h1>Numerai Signals</h1>
			<span class="data-version">v2.1 Alpha</span>
		</div>
		{#if loading}
			<span class="loading-indicator">Loading...</span>
		{/if}
	</header>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<div class="tabs">
		<button class:active={activeTab === 'overview'} onclick={() => (activeTab = 'overview')}>Overview</button>
		<button class:active={activeTab === 'deploy'} onclick={() => (activeTab = 'deploy')}>Deploy</button>
		<button class:active={activeTab === 'exogenous'} onclick={() => (activeTab = 'exogenous')}>Exogenous</button>
		<button class:active={activeTab === 'experiments'} onclick={() => (activeTab = 'experiments')}>Experiments</button>
		<button class:active={activeTab === 'models'} onclick={() => (activeTab = 'models')}>Models</button>
		<button class:active={activeTab === 'rounds'} onclick={() => (activeTab = 'rounds')}>Rounds</button>
	</div>

	<!-- Overview Tab -->
	{#if activeTab === 'overview'}
		<div class="cards">
			<MetricCard
				label="Active Runs"
				value={$mlOverview?.active_runs?.toString() ?? '0'}
				sub="Currently training"
				color={($mlOverview?.active_runs ?? 0) > 0 ? 'var(--blue)' : ''}
			/>
			<MetricCard
				label="Best Correlation"
				value={$mlOverview?.best_model ? fmt($mlOverview.best_model.correlation, 4) : '\u2014'}
				sub={$mlOverview?.best_model?.name ?? 'No production model'}
				color="var(--green)"
			/>
			<MetricCard
				label="Best Sharpe"
				value={$mlOverview?.best_model ? fmt($mlOverview.best_model.sharpe, 2) : '\u2014'}
				sub={$mlOverview?.best_model?.name ?? 'No production model'}
				color="var(--blue)"
			/>
			<MetricCard
				label="Max Drawdown"
				value={$mlOverview?.best_model ? fmt($mlOverview.best_model.max_drawdown, 4) : '\u2014'}
				sub={$mlOverview?.best_model?.name ?? 'No production model'}
				color="var(--red)"
			/>
			<MetricCard
				label="Total Cost"
				value={$mlOverview ? `$${$mlOverview.total_cost_usd.toFixed(2)}` : '\u2014'}
				sub="Last 10 runs"
				color="var(--orange)"
			/>
			<MetricCard
				label="Latest Round"
				value={$mlOverview?.latest_round ? `#${$mlOverview.latest_round.round_number}` : '\u2014'}
				sub={$mlOverview?.latest_round?.status ?? 'No submissions'}
			/>
		</div>

		{#if $mlOverview?.recent_runs}
			<TrainingProgress runs={$mlOverview.recent_runs} oncancel={handleCancelRun} />
		{/if}

		{#if $mlOverview?.recent_runs && $mlOverview.recent_runs.length > 0}
			<div class="section">
				<h2>Recent Runs</h2>
				<div class="table-wrapper">
					<table>
						<thead>
							<tr>
								<th>ID</th>
								<th>Model Type</th>
								<th>Status</th>
								<th class="num">Corr</th>
								<th class="num">MMC</th>
								<th class="num">Sharpe</th>
								<th class="num">Feat Exp</th>
								<th class="num">Max DD</th>
								<th>Instance</th>
								<th class="num">Cost</th>
								<th>Started</th>
							</tr>
						</thead>
						<tbody>
							{#each $mlOverview.recent_runs as run}
								<tr class="clickable" onclick={() => loadRunMetrics(run.id)}>
									<td class="mono">#{run.id}</td>
									<td>{run.model_type}</td>
									<td><span class="status-dot" style="color: {statusColor(run.status)}">{run.status}</span></td>
									<td class="num">{fmt(run.correlation)}</td>
									<td class="num">{fmt(run.mmc)}</td>
									<td class="num">{fmt(run.sharpe, 2)}</td>
									<td class="num">{fmt(run.feature_exposure)}</td>
									<td class="num">{fmt(run.max_drawdown)}</td>
									<td class="dim">{run.instance_type ?? '\u2014'}</td>
									<td class="num">{run.cost_usd !== null ? `$${run.cost_usd.toFixed(2)}` : '\u2014'}</td>
									<td class="dim">{run.started_at || '\u2014'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		{#if selectedRunId !== null}
			<div class="section">
				<h2>Loss Curve &mdash; Run #{selectedRunId}</h2>
				{#if metricsLoading}
					<p class="placeholder">Loading metrics...</p>
				{:else if metricsError}
					<div class="error-box">{metricsError}</div>
				{:else}
					<LossChart metrics={epochMetrics} />
				{/if}
			</div>
		{/if}

	<!-- Deploy Tab -->
	{:else if activeTab === 'deploy'}
		<form class="deploy-form" onsubmit={(e) => { e.preventDefault(); handleDeploy(); }}>
			<div class="deploy-grid">
				<div class="deploy-section deploy-main">
					<h2>Run Configuration</h2>
					<div class="field-grid">
						<label>
							<span>Experiment Name</span>
							<input type="text" bind:value={deployExpName} placeholder="e.g. signals-alpha-v1" required />
						</label>
						<label>
							<span>Description</span>
							<input type="text" bind:value={deployDescription} placeholder="Optional" />
						</label>
					</div>
					<div class="field-grid three-col">
						<label>
							<span>Data Version</span>
							<select bind:value={deployDataVersion}>
								<option value="v2.1">v2.1 Alpha (Jul 2025)</option>
							</select>
						</label>
						<label>
							<span>Model Type</span>
							<select bind:value={deployModelType}>
								<option value="lgbm">LightGBM</option>
								<option value="catboost">CatBoost</option>
							</select>
						</label>
						<label>
							<span>Instance Type</span>
							<select bind:value={deployInstanceType}>
								{#each Object.entries(instanceRates) as [type, info]}
									<option value={type}>{type} ({info.spec})</option>
								{/each}
							</select>
						</label>
					</div>

					<h2>Model Parameters</h2>
					<div class="field-grid three-col">
						<label>
							<span>{deployModelType === 'catboost' ? 'Iterations' : 'Num Rounds'}</span>
							<input type="number" bind:value={lgbmNumRounds} min="100" max="50000" step="100" />
						</label>
						<label>
							<span>Learning Rate</span>
							<input type="number" bind:value={lgbmLearningRate} min="0.001" max="0.1" step="0.001" />
						</label>
						<label>
							<span>Max Depth</span>
							<input type="number" bind:value={lgbmMaxDepth} min="-1" max="20" />
						</label>
						<label>
							<span>Early Stopping</span>
							<input type="number" bind:value={lgbmEarlyStopping} min="10" max="1000" step="10" />
						</label>
						<label>
							<span>Max Training Eras</span>
							<input type="number" bind:value={deployMaxTrainEras} min="50" max="2000" step="50" />
						</label>
						{#if deployModelType === 'lgbm'}
							<label>
								<span>Num Leaves</span>
								<input type="number" bind:value={lgbmNumLeaves} min="16" max="4096" step="16" />
							</label>
							<label>
								<span>Feature Fraction</span>
								<input type="number" bind:value={lgbmFeatureFraction} min="0.01" max="1.0" step="0.01" />
							</label>
							<label>
								<span>Bagging Fraction</span>
								<input type="number" bind:value={lgbmBaggingFraction} min="0.1" max="1.0" step="0.05" />
							</label>
						{/if}
					</div>
				</div>

				<div class="deploy-sidebar">
					<div class="deploy-section">
						<h2>Signals Options</h2>
						<div class="toggle-stack">
							<label class="toggle-label">
								<span class="toggle-switch" class:on={deployNeutralizerAware}></span>
								<input type="checkbox" class="sr-only" bind:checked={deployNeutralizerAware} />
								<div>
									<span class="toggle-title">Neutralizer-Aware</span>
									<span class="toggle-desc">Train using train_neutralizer.parquet matrix for Alpha/MPC scoring</span>
								</div>
							</label>
							<label class="toggle-label">
								<span class="toggle-switch" class:on={deploySampleWeightAware}></span>
								<input type="checkbox" class="sr-only" bind:checked={deploySampleWeightAware} />
								<div>
									<span class="toggle-title">Sample Weights</span>
									<span class="toggle-desc">Apply train_sample_weights.parquet during training</span>
								</div>
							</label>
							<label class="toggle-label">
								<span class="toggle-switch" class:on={deployMultiTarget}></span>
								<input type="checkbox" class="sr-only" bind:checked={deployMultiTarget} />
								<div>
									<span class="toggle-title">Multi-Target Training</span>
									<span class="toggle-desc">Train on all targets, ensemble via rank-average</span>
								</div>
							</label>
							<label class="toggle-label">
								<span class="toggle-switch" class:on={deployUpload}></span>
								<input type="checkbox" class="sr-only" bind:checked={deployUpload} />
								<div>
									<span class="toggle-title">Upload to Signals</span>
									<span class="toggle-desc">Auto-submit predictions via SignalsAPI after training</span>
								</div>
							</label>
							<label class="toggle-label">
								<span class="toggle-switch" class:on={deployExogenousData}></span>
								<input type="checkbox" class="sr-only" bind:checked={deployExogenousData} />
								<div>
									<span class="toggle-title">Exogenous Options Data</span>
									<span class="toggle-desc">Join IV rank, skew, term structure from Tastytrade as extra features</span>
								</div>
							</label>
						</div>
						{#if deployExogenousData}
							<div class="exogenous-config">
								<label>
									<span>Symbols</span>
									<textarea
										bind:value={exogenousSymbols}
										rows="2"
										placeholder="SPY,QQQ,AAPL,..."
									></textarea>
								</label>
								<p class="exogenous-hint">Comma-separated tickers. Market metrics (IV rank, IV percentile, IV index, skew, term structure) will be fetched from Tastytrade at training time and joined as features.</p>
							</div>
						{/if}
					</div>

					<div class="deploy-section">
						<h2>Neutralization</h2>
						<div class="neutralization-control">
							<div class="neutralization-header">
								<span class="neutralization-value">{deployNeutralizationPct}%</span>
							</div>
							<input type="range" bind:value={deployNeutralizationPct} min="0" max="100" step="5" />
							<div class="neutralization-labels">
								<span>None</span>
								<span>Full</span>
							</div>
						</div>
					</div>

					<div class="deploy-section deploy-launch-section">
						{#if estimatedCost}
							<div class="cost-estimate">
								<div class="cost-row">
									<span class="cost-label">Est. time</span>
									<span class="cost-value">~{estimatedCost.minutes} min</span>
								</div>
								<div class="cost-row">
									<span class="cost-label">Est. cost</span>
									<span class="cost-value cost-highlight">${estimatedCost.low} &ndash; ${estimatedCost.high}</span>
								</div>
								<div class="cost-row">
									<span class="cost-label">Rate</span>
									<span class="cost-value">${instanceRates[deployInstanceType]?.rate}/hr</span>
								</div>
							</div>
						{/if}
						<button type="submit" class="launch-btn" disabled={!deployExpName.trim() || deployLoading}>
							{#if deployLoading}
								<span class="launch-spinner"></span> Launching...
							{:else}
								Launch Training
							{/if}
						</button>
					</div>
				</div>
			</div>
		</form>

	<!-- Exogenous Tab -->
	{:else if activeTab === 'exogenous'}
		<!-- Sources -->
		<div class="section">
			<h2>Data Sources</h2>
			<div class="exo-sources">
				{#each exoSources as src}
					<div class="exo-source-card" class:expanded={expandedSource === src.id}>
						<button class="exo-source-header" onclick={() => expandedSource = expandedSource === src.id ? null : src.id}>
							<div class="exo-source-title">
								<span class="exo-status-dot" class:active={src.status === 'active'} class:planned={src.status === 'planned'}></span>
								<span class="exo-source-name">{src.name}</span>
								<span class="exo-source-badge" class:active={src.status === 'active'} class:planned={src.status === 'planned'}>
									{src.status}
								</span>
							</div>
							<div class="exo-source-stats">
								<span class="exo-stat"><strong>{src.symbols}</strong> symbols</span>
								<span class="exo-stat-sep">/</span>
								<span class="exo-stat"><strong>{src.features.length}</strong> features</span>
								<span class="exo-stat-sep">/</span>
								<span class="exo-stat"><strong>{(src.symbols / src.universe * 100).toFixed(1)}%</strong> coverage</span>
							</div>
						</button>
						{#if expandedSource === src.id}
							<div class="exo-source-detail">
								<div class="exo-detail-row">
									<span class="exo-detail-label">Provider</span>
									<span class="exo-detail-value mono">{src.provider}</span>
								</div>
								<div class="exo-detail-row">
									<span class="exo-detail-label">History</span>
									<span class="exo-detail-value">{src.historyDays > 0 ? `${src.historyDays} days` : 'Not yet collecting'}</span>
								</div>
								<div class="exo-detail-row">
									<span class="exo-detail-label">Universe coverage</span>
									<span class="exo-detail-value">{src.symbols} / ~{src.universe.toLocaleString()} stocks</span>
								</div>
								<div class="exo-detail-row">
									<span class="exo-detail-label">Metrics</span>
									<span class="exo-detail-value">IV rank, IV percentile, IV index, 5d change, skew, term structure</span>
								</div>
							</div>
						{/if}
					</div>
				{/each}
				<div class="exo-source-card exo-add-card">
					<div class="exo-add-inner">
						<span class="exo-add-icon">+</span>
						<span class="exo-add-text">Add Data Source</span>
						<span class="exo-add-sub">FRED macro, sentiment, alternative data</span>
					</div>
				</div>
			</div>
		</div>

		<!-- Feature Catalog -->
		<div class="section">
			<h2>Feature Catalog</h2>
			<div class="table-wrapper">
				<table class="exo-table">
					<thead>
						<tr>
							<th>Feature</th>
							<th>Source</th>
							<th>Description</th>
							<th class="num">Coverage</th>
							<th class="num">Signal</th>
							<th class="num">Runs</th>
						</tr>
					</thead>
					<tbody>
						{#each allFeatures as feat}
							<tr>
								<td class="mono">{feat.name}</td>
								<td>{feat.source}</td>
								<td class="exo-feat-desc">{feat.desc}</td>
								<td class="num">{feat.coverage.toFixed(1)}%</td>
								<td class="num">
									<span class="signal-badge" style="color: {signalColor(feat.signal)}">
										{feat.signal}
									</span>
								</td>
								<td class="num">{feat.usedInRuns}</td>
							</tr>
						{/each}
						<tr class="derived-row">
							<td class="mono">opt_has_data</td>
							<td>derived</td>
							<td class="exo-feat-desc">Binary flag: 1 if stock has options data, 0 otherwise</td>
							<td class="num">100%</td>
							<td class="num"><span class="signal-badge" style="color: var(--text-muted)">low</span></td>
							<td class="num">0</td>
						</tr>
						<tr class="derived-row">
							<td class="mono">opt_iv_rank_zscore</td>
							<td>derived</td>
							<td class="exo-feat-desc">Cross-sectional z-score of IV rank per era</td>
							<td class="num">9.7%</td>
							<td class="num"><span class="signal-badge" style="color: var(--green)">high</span></td>
							<td class="num">0</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Coverage -->
		<div class="section">
			<h2>Coverage Estimates</h2>
			<div class="coverage-grid">
				<div class="coverage-panel">
					<h3>By Sector</h3>
					{#each coverageBySector as row}
						<div class="coverage-row">
							<span class="coverage-label">{row.sector}</span>
							<div class="coverage-bar-track">
								<div class="coverage-bar-fill" style="width: {row.pct}%"></div>
							</div>
							<span class="coverage-pct">{row.pct}%</span>
						</div>
					{/each}
				</div>
				<div class="coverage-panel">
					<h3>By Market Cap</h3>
					{#each coverageByMcap as row}
						<div class="coverage-row">
							<span class="coverage-label">{row.tier}</span>
							<div class="coverage-bar-track">
								<div class="coverage-bar-fill" style="width: {row.pct}%"></div>
							</div>
							<span class="coverage-pct">{row.pct}%</span>
						</div>
					{/each}
				</div>
			</div>
		</div>

		<!-- Symbol List -->
		<div class="section">
			<div class="symbol-header">
				<h2>Tracked Symbols ({parsedSymbols.length})</h2>
				<input type="text" class="symbol-search" bind:value={symbolSearch} placeholder="Filter symbols..." />
			</div>
			<div class="symbol-grid">
				{#each filteredSymbols as sym}
					<span class="symbol-chip">{sym}</span>
				{/each}
				{#if filteredSymbols.length === 0}
					<span class="dim">No symbols match</span>
				{/if}
			</div>
			<p class="symbol-hint">Edit the symbol list in the Deploy tab under Exogenous Options Data.</p>
		</div>

	<!-- Experiments Tab -->
	{:else if activeTab === 'experiments'}
		<div class="section">
			{#if $mlExperiments.items.length === 0 && !$mlExperiments.loading}
				<p class="placeholder">No Signals experiments yet. Launch a training run to get started.</p>
			{:else}
				<div class="table-wrapper">
					<table>
						<thead>
							<tr>
								<th></th>
								<th>Name</th>
								<th>Status</th>
								<th class="num">Runs</th>
								<th class="num">Best Corr</th>
								<th>Created</th>
							</tr>
						</thead>
						<tbody>
							{#each $mlExperiments.items as exp}
								<tr class="clickable" onclick={() => toggleExperiment(exp)}>
									<td class="expand-icon">{expandedExp === exp.id ? '\u25BC' : '\u25B6'}</td>
									<td class="mono">{exp.name}</td>
									<td><span class="status-dot" style="color: {statusColor(exp.status)}">{exp.status}</span></td>
									<td class="num">{exp.run_count}</td>
									<td class="num">{fmt(exp.best_corr)}</td>
									<td class="dim">{exp.created_at}</td>
								</tr>

								{#if expandedExp === exp.id}
									<tr class="expanded-row">
										<td colspan="6">
											{#if expRunsLoading}
												<p class="loading-text">Loading runs...</p>
											{:else if expRuns.length === 0}
												<p class="loading-text">No runs in this experiment</p>
											{:else}
												<div class="inner-table-wrapper">
													<table class="inner-table">
														<thead>
															<tr>
																<th>ID</th>
																<th>Type</th>
																<th>Status</th>
																<th class="num">Corr</th>
																<th class="num">MMC</th>
																<th class="num">Sharpe</th>
																<th class="num">Feat Exp</th>
																<th class="num">Max DD</th>
																<th class="num">Cost</th>
																<th>Hyperparams</th>
															</tr>
														</thead>
														<tbody>
															{#each expRuns as run}
																<tr>
																	<td class="mono">#{run.id}</td>
																	<td>{run.model_type}</td>
																	<td><span class="status-dot" style="color: {statusColor(run.status)}">{run.status}</span></td>
																	<td class="num">{fmt(run.correlation)}</td>
																	<td class="num">{fmt(run.mmc)}</td>
																	<td class="num">{fmt(run.sharpe, 2)}</td>
																	<td class="num">{fmt(run.feature_exposure)}</td>
																	<td class="num">{fmt(run.max_drawdown)}</td>
																	<td class="num">{run.cost_usd !== null ? `$${run.cost_usd.toFixed(2)}` : '\u2014'}</td>
																	<td class="mono params">{run.hyperparams_json ?? '\u2014'}</td>
																</tr>
															{/each}
														</tbody>
													</table>
												</div>
												<ModelComparisonChart runs={expRuns} />
											{/if}
										</td>
									</tr>
								{/if}
							{/each}
						</tbody>
					</table>
				</div>

				{#if $mlExperiments.hasMore}
					<button class="load-more" onclick={() => mlExperiments.load()}>
						{$mlExperiments.loading ? 'Loading...' : 'Load More'}
					</button>
				{/if}
			{/if}
		</div>

	<!-- Models Tab -->
	{:else if activeTab === 'models'}
		<div class="section">
			{#if $mlModels.length === 0}
				<p class="placeholder">No registered Signals models. Promote a run to create one.</p>
			{:else}
				<div class="table-wrapper">
					<table>
						<thead>
							<tr>
								<th>Name</th>
								<th>Type</th>
								<th>Stage</th>
								<th class="num">Version</th>
								<th class="num">Corr</th>
								<th class="num">MMC</th>
								<th class="num">Sharpe</th>
								<th class="num">Feat Exp</th>
								<th class="num">Max DD</th>
								<th>Actions</th>
							</tr>
						</thead>
						<tbody>
							{#each $mlModels as model}
								<tr>
									<td class="mono">{model.name}</td>
									<td>{model.model_type}</td>
									<td>
										<span class="stage-badge" style="background: {stageBadgeBg(model.stage)}; color: {stageColor(model.stage)}">
											{model.stage}
										</span>
									</td>
									<td class="num">v{model.version}</td>
									<td class="num">{fmt(model.correlation)}</td>
									<td class="num">{fmt(model.mmc)}</td>
									<td class="num">{fmt(model.sharpe, 2)}</td>
									<td class="num">{fmt(model.feature_exposure)}</td>
									<td class="num">{fmt(model.max_drawdown)}</td>
									<td class="actions">
										{#if model.stage === 'dev'}
											<button class="promote-btn staging" onclick={() => promoteModel(model.id, 'staging')}>Staging</button>
										{/if}
										{#if model.stage === 'staging'}
											<button class="promote-btn prod" onclick={() => promoteModel(model.id, 'prod')}>Prod</button>
										{/if}
										{#if model.stage === 'prod'}
											<span class="dim">In production</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

	<!-- Rounds Tab -->
	{:else if activeTab === 'rounds'}
		<div class="section">
			{#if $mlRounds.length === 0}
				<p class="placeholder">No Signals submissions yet. Round history will appear here.</p>
			{:else}
				<div class="table-wrapper">
					<table>
						<thead>
							<tr>
								<th class="num">Round</th>
								<th>Model</th>
								<th>Status</th>
								<th class="num">Live Corr</th>
								<th class="num">Resolved Corr</th>
								<th class="num">Payout (NMR)</th>
								<th>Submitted</th>
							</tr>
						</thead>
						<tbody>
							{#each $mlRounds as round}
								<tr>
									<td class="num mono">#{round.round_number}</td>
									<td>{round.model_name}</td>
									<td><span class="status-dot" style="color: {statusColor(round.status)}">{round.status}</span></td>
									<td class="num" class:positive={round.live_corr !== null && round.live_corr > 0} class:negative={round.live_corr !== null && round.live_corr < 0}>
										{fmt(round.live_corr)}
									</td>
									<td class="num" class:positive={round.resolved_corr !== null && round.resolved_corr > 0} class:negative={round.resolved_corr !== null && round.resolved_corr < 0}>
										{fmt(round.resolved_corr)}
									</td>
									<td class="num">{round.payout_nmr !== null ? round.payout_nmr.toFixed(2) : '\u2014'}</td>
									<td class="dim">{round.submitted_at ?? '\u2014'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

	{/if}
</div>

<style>
	.ml-page header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1rem;
	}

	h1 { font-size: 1.5rem; margin: 0; }
	h2 { font-size: 1rem; margin: 0 0 0.75rem 0; color: var(--text); }

	.data-version {
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--purple);
		background: rgba(130, 80, 223, 0.08);
		padding: 0.15rem 0.5rem;
		border-radius: 10px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.loading-indicator { color: var(--text-secondary); font-size: 0.8rem; }
	.error { color: var(--red); }
	.error-box {
		color: var(--red);
		background: rgba(255, 107, 107, 0.1);
		border: 1px solid var(--red);
		border-radius: 6px;
		padding: 1rem;
		font-size: 0.85rem;
		font-family: var(--font-mono);
	}

	.tabs {
		display: flex;
		gap: 0;
		margin-bottom: 1rem;
		border-bottom: 2px solid var(--border-light);
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
		scrollbar-width: none;
	}

	.tabs::-webkit-scrollbar { display: none; }

	.tabs button {
		background: none;
		border: none;
		padding: 0.5rem 1rem;
		cursor: pointer;
		color: var(--text-secondary);
		font-size: 0.85rem;
		font-weight: 500;
		border-bottom: 2px solid transparent;
		margin-bottom: -2px;
		transition: color 0.15s, border-color 0.15s;
		white-space: nowrap;
		flex-shrink: 0;
	}

	.tabs button:hover { color: var(--text); }
	.tabs button.active {
		color: var(--purple);
		border-bottom-color: var(--purple);
	}

	.cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: 0.6rem;
		margin-bottom: 1rem;
	}

	.section { margin-bottom: 1.25rem; }
	.table-wrapper { overflow-x: auto; -webkit-overflow-scrolling: touch; }

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.78rem;
	}

	th {
		text-align: left;
		padding: 0.4rem 0.5rem;
		border-bottom: 2px solid var(--border);
		color: var(--text-secondary);
		font-weight: 600;
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		white-space: nowrap;
	}

	td {
		padding: 0.35rem 0.5rem;
		border-bottom: 1px solid var(--border-light);
	}

	tr:hover { background: var(--hover-bg); }
	tr.expanded-row:hover { background: transparent; }
	tr.expanded-row td { padding: 0.75rem; background: var(--bg-page); }

	.clickable { cursor: pointer; }

	.mono {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.73rem;
	}

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.dim { color: var(--text-muted); font-size: 0.73rem; }

	.status-dot { font-weight: 600; font-size: 0.75rem; }

	.stage-badge {
		display: inline-block;
		padding: 0.15rem 0.5rem;
		border-radius: 12px;
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.positive { color: var(--green); }
	.negative { color: var(--red); }

	.expand-icon {
		width: 1.5rem;
		font-size: 0.6rem;
		color: var(--text-muted);
	}

	.inner-table-wrapper {
		margin-bottom: 0.75rem;
		overflow-x: auto;
	}

	.inner-table {
		font-size: 0.73rem;
	}

	.inner-table th {
		font-size: 0.6rem;
		border-bottom-width: 1px;
	}

	.params {
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.65rem;
		color: var(--text-muted);
	}

	.loading-text {
		color: var(--text-muted);
		font-size: 0.8rem;
		padding: 0.5rem;
	}

	.actions { white-space: nowrap; }

	.promote-btn {
		border: none;
		padding: 0.25rem 0.6rem;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.7rem;
		font-weight: 600;
		transition: opacity 0.15s;
	}

	.promote-btn:hover { opacity: 0.8; }

	.promote-btn.staging {
		background: var(--badge-orange);
		color: var(--orange);
	}

	.promote-btn.prod {
		background: var(--badge-green);
		color: var(--green);
	}

	.load-more {
		display: block;
		margin: 0.75rem auto;
		background: var(--bg-input);
		border: 1px solid var(--border);
		padding: 0.4rem 1rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.8rem;
		color: var(--text-secondary);
	}

	.load-more:hover { color: var(--text); }

	.placeholder {
		color: var(--text-secondary);
		text-align: center;
		padding: 3rem;
	}

	/* ── Exogenous tab ── */
	.exo-sources {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
		gap: 0.6rem;
	}

	.exo-source-card {
		background: var(--bg-card);
		border: 1px solid var(--border-light);
		border-radius: 8px;
		overflow: hidden;
		box-shadow: var(--shadow-sm);
	}

	.exo-source-header {
		width: 100%;
		background: none;
		border: none;
		padding: 0.75rem 0.85rem;
		cursor: pointer;
		text-align: left;
		color: var(--text);
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		transition: background 0.15s;
	}

	.exo-source-header:hover { background: var(--hover-bg); }

	.exo-source-title {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}

	.exo-status-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		flex-shrink: 0;
		background: var(--text-muted);
	}

	.exo-status-dot.active { background: var(--green); }
	.exo-status-dot.planned { background: var(--orange); }

	.exo-source-name {
		font-size: 0.82rem;
		font-weight: 600;
	}

	.exo-source-badge {
		font-size: 0.58rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 0.1rem 0.35rem;
		border-radius: 6px;
		background: var(--badge-muted);
		color: var(--text-muted);
	}

	.exo-source-badge.active { background: var(--badge-green); color: var(--green); }
	.exo-source-badge.planned { background: var(--badge-orange); color: var(--orange); }

	.exo-source-stats {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		font-size: 0.7rem;
		color: var(--text-secondary);
	}

	.exo-stat strong {
		color: var(--text);
		font-variant-numeric: tabular-nums;
	}

	.exo-stat-sep {
		color: var(--border);
		font-size: 0.6rem;
	}

	.exo-source-detail {
		border-top: 1px solid var(--border-light);
		padding: 0.6rem 0.85rem;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		background: var(--bg-page);
	}

	.exo-detail-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 0.7rem;
	}

	.exo-detail-label {
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		font-size: 0.62rem;
		font-weight: 600;
	}

	.exo-detail-value {
		color: var(--text-secondary);
		text-align: right;
		max-width: 60%;
	}

	.exo-add-card {
		border-style: dashed;
		border-color: var(--border);
		background: transparent;
	}

	.exo-add-inner {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 1.25rem;
		gap: 0.25rem;
		color: var(--text-muted);
	}

	.exo-add-icon {
		font-size: 1.5rem;
		line-height: 1;
		font-weight: 300;
		color: var(--border);
	}

	.exo-add-text {
		font-size: 0.78rem;
		font-weight: 600;
	}

	.exo-add-sub {
		font-size: 0.65rem;
		color: var(--text-muted);
	}

	/* Feature catalog */
	.exo-table { font-size: 0.73rem; }

	.exo-feat-desc {
		color: var(--text-secondary);
		font-size: 0.7rem;
		max-width: 320px;
	}

	.signal-badge {
		font-size: 0.65rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.derived-row td { color: var(--text-muted); }
	.derived-row .mono { font-style: italic; }

	/* Coverage */
	.coverage-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.75rem;
	}

	.coverage-panel {
		background: var(--bg-card);
		border: 1px solid var(--border-light);
		border-radius: 8px;
		padding: 0.75rem 0.85rem;
		box-shadow: var(--shadow-sm);
	}

	.coverage-panel h3 {
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-secondary);
		margin: 0 0 0.5rem 0;
	}

	.coverage-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.3rem;
	}

	.coverage-label {
		font-size: 0.7rem;
		color: var(--text-secondary);
		width: 100px;
		flex-shrink: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.coverage-bar-track {
		flex: 1;
		height: 6px;
		background: var(--bg-input);
		border-radius: 3px;
		overflow: hidden;
	}

	.coverage-bar-fill {
		height: 100%;
		background: var(--purple);
		border-radius: 3px;
		transition: width 0.3s;
	}

	.coverage-pct {
		font-size: 0.68rem;
		font-variant-numeric: tabular-nums;
		color: var(--text-muted);
		width: 32px;
		text-align: right;
		flex-shrink: 0;
	}

	/* Symbol list */
	.symbol-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.5rem;
	}

	.symbol-header h2 { margin-bottom: 0; }

	.symbol-search {
		padding: 0.3rem 0.5rem;
		background: var(--bg-input);
		border: 1px solid var(--border);
		border-radius: 5px;
		color: var(--text);
		font-size: 0.75rem;
		font-family: 'SF Mono', 'Consolas', monospace;
		width: 160px;
	}

	.symbol-search:focus {
		outline: none;
		border-color: var(--purple);
		box-shadow: 0 0 0 2px rgba(130, 80, 223, 0.15);
	}

	.symbol-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}

	.symbol-chip {
		display: inline-block;
		padding: 0.2rem 0.5rem;
		background: var(--bg-card);
		border: 1px solid var(--border-light);
		border-radius: 4px;
		font-size: 0.72rem;
		font-family: 'SF Mono', 'Consolas', monospace;
		font-weight: 500;
		color: var(--text);
	}

	.symbol-hint {
		font-size: 0.68rem;
		color: var(--text-muted);
		margin: 0.5rem 0 0 0;
	}

	/* ── Deploy tab ── */
	.deploy-form {
		width: 100%;
		max-width: 820px;
	}

	.deploy-grid {
		display: grid;
		grid-template-columns: 1fr 260px;
		gap: 0.75rem;
		align-items: start;
	}

	.deploy-section {
		background: var(--bg-card);
		border: 1px solid var(--border-light);
		border-radius: 8px;
		padding: 0.85rem 1rem;
		box-shadow: var(--shadow-sm);
	}

	.deploy-main { margin-bottom: 0; }
	.deploy-sidebar { display: flex; flex-direction: column; gap: 1rem; }

	.deploy-form h2 {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-secondary);
		margin: 0 0 0.5rem 0;
		padding-bottom: 0.35rem;
		border-bottom: 1px solid var(--border-light);
	}

	.deploy-form h2:not(:first-child) {
		margin-top: 0.85rem;
	}

	.deploy-form label > span:first-child {
		display: block;
		font-size: 0.65rem;
		font-weight: 600;
		color: var(--text-muted);
		margin-bottom: 0.2rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.deploy-form input[type="text"],
	.deploy-form input[type="number"],
	.deploy-form select {
		width: 100%;
		padding: 0.35rem 0.5rem;
		background: var(--bg-input);
		border: 1px solid var(--border);
		border-radius: 5px;
		color: var(--text);
		font-size: 0.75rem;
		font-family: 'SF Mono', 'Consolas', monospace;
		transition: border-color 0.15s;
		min-height: 0;
	}

	.deploy-form input[type="range"] {
		width: 100%;
		accent-color: var(--purple);
		margin-top: 0.35rem;
	}

	.deploy-form input:focus,
	.deploy-form select:focus {
		outline: none;
		border-color: var(--purple);
		box-shadow: 0 0 0 2px rgba(130, 80, 223, 0.15);
	}

	.field-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.5rem;
	}

	.field-grid.three-col { grid-template-columns: 1fr 1fr 1fr; }

	/* Toggle switches */
	.toggle-stack {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
	}

	.toggle-label {
		display: flex;
		align-items: flex-start;
		gap: 0.65rem;
		cursor: pointer;
		padding: 0.5rem;
		border-radius: 6px;
		transition: background 0.15s;
	}

	.toggle-label:hover { background: var(--bg-input); }

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border-width: 0;
	}

	.toggle-switch {
		position: relative;
		flex-shrink: 0;
		width: 2.25rem;
		height: 1.25rem;
		background: var(--border);
		border-radius: 0.625rem;
		transition: background 0.2s;
		margin-top: 0.1rem;
	}

	.toggle-switch::after {
		content: '';
		position: absolute;
		top: 2px;
		left: 2px;
		width: 1rem;
		height: 1rem;
		background: white;
		border-radius: 50%;
		transition: transform 0.2s;
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
	}

	.toggle-switch.on {
		background: var(--purple);
	}

	.toggle-switch.on::after {
		transform: translateX(1rem);
	}

	.toggle-title {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--text);
		text-transform: none;
		letter-spacing: normal;
		display: block;
	}

	.toggle-desc {
		font-size: 0.7rem;
		color: var(--text-muted);
		text-transform: none;
		letter-spacing: normal;
		font-weight: normal;
		line-height: 1.35;
		display: block;
	}

	/* Exogenous config */
	.exogenous-config {
		margin-top: 0.5rem;
		padding: 0.75rem;
		background: var(--bg-input);
		border-radius: 6px;
		border: 1px solid var(--border-light);
	}

	.exogenous-config label > span:first-child {
		display: block;
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--text-muted);
		margin-bottom: 0.3rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.exogenous-config textarea {
		width: 100%;
		padding: 0.5rem 0.6rem;
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text);
		font-size: 0.75rem;
		font-family: 'SF Mono', 'Consolas', monospace;
		resize: vertical;
		line-height: 1.5;
	}

	.exogenous-config textarea:focus {
		outline: none;
		border-color: var(--purple);
		box-shadow: 0 0 0 2px rgba(130, 80, 223, 0.15);
	}

	.exogenous-hint {
		font-size: 0.68rem;
		color: var(--text-muted);
		margin: 0.4rem 0 0 0;
		line-height: 1.4;
	}

	/* Neutralization */
	.neutralization-control {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.neutralization-header {
		text-align: center;
	}

	.neutralization-value {
		font-size: 1.25rem;
		font-weight: 700;
		color: var(--purple);
		font-variant-numeric: tabular-nums;
	}

	.neutralization-labels {
		display: flex;
		justify-content: space-between;
		font-size: 0.65rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	/* Cost estimate */
	.deploy-launch-section {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 0.75rem;
	}

	.cost-estimate {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.cost-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 0.78rem;
	}

	.cost-label {
		color: var(--text-muted);
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.cost-value {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.8rem;
		color: var(--text-secondary);
		font-variant-numeric: tabular-nums;
	}

	.cost-highlight {
		color: var(--orange);
		font-weight: 600;
	}

	/* Launch button */
	.launch-btn {
		width: 100%;
		background: var(--purple);
		border: none;
		padding: 0.55rem 1.5rem;
		border-radius: 6px;
		cursor: pointer;
		color: white;
		font-size: 0.8rem;
		font-weight: 700;
		transition: opacity 0.15s, box-shadow 0.15s, transform 0.1s;
		box-shadow: 0 2px 4px rgba(130, 80, 223, 0.25);
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		min-height: 0;
	}

	.launch-btn:hover:not(:disabled) {
		opacity: 0.9;
		transform: translateY(-1px);
		box-shadow: 0 4px 8px rgba(130, 80, 223, 0.3);
	}

	.launch-btn:active:not(:disabled) {
		transform: translateY(0);
	}

	.launch-btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.launch-spinner {
		display: inline-block;
		width: 0.9rem;
		height: 0.9rem;
		border: 2px solid rgba(255, 255, 255, 0.3);
		border-top-color: white;
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* ── Responsive ── */
	@media (max-width: 900px) {
		.cards { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
		.field-grid.three-col { grid-template-columns: 1fr 1fr; }
		.deploy-grid { grid-template-columns: 1fr; }
		.exo-sources { grid-template-columns: 1fr; }
		.coverage-grid { grid-template-columns: 1fr; }
	}

	@media (max-width: 640px) {
		.cards { grid-template-columns: repeat(2, 1fr); }
		.deploy-section { padding: 1rem; }
	}

	@media (max-width: 480px) {
		h1 { font-size: 1.25rem; }
		.cards { grid-template-columns: 1fr 1fr; gap: 0.4rem; }
		.field-grid { grid-template-columns: 1fr; }
		.field-grid.three-col { grid-template-columns: 1fr; }
		.deploy-section { padding: 0.85rem; border-radius: 8px; }
		.deploy-grid { gap: 0.75rem; }
		.tabs button { padding: 0.5rem 0.75rem; font-size: 0.8rem; }
	}
</style>
