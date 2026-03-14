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

	let activeTab = $state<'overview' | 'deploy' | 'data' | 'experiments' | 'models' | 'rounds'>('overview');
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

	// Signals v2.1 data files reference
	const dataFiles = [
		{ name: 'train.parquet', desc: 'Training data for your model' },
		{ name: 'train_neutralizer.parquet', desc: 'Neutralization matrix for training eras' },
		{ name: 'train_sample_weights.parquet', desc: 'Sample weights vector for training eras' },
		{ name: 'validation.parquet', desc: 'Validation data, expands weekly with new eras' },
		{ name: 'validation_neutralizer.parquet', desc: 'Neutralization matrix for validation eras' },
		{ name: 'validation_sample_weights.parquet', desc: 'Sample weights vector for validation eras' },
		{ name: 'validation_example_preds.parquet', desc: 'Example predictions for diagnostics' },
		{ name: 'live.parquet', desc: 'Live data for predictions, changes daily' },
		{ name: 'live_example_preds.parquet', desc: 'Example live predictions for first submission' },
	];

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
				},
			};
			if (deployDescription.trim()) {
				config.description = deployDescription.trim();
			}
			const result = await triggerTraining(config);
			addToast(`Signals training started: Run #${result.run_id}`, 'success');
			activeTab = 'overview';
			await loadMlOverview();
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
				loadMlOverview(),
				mlExperiments.refresh(),
				loadMlModels(),
				loadMlRounds()
			]);
			if (($mlOverview?.active_runs ?? 0) > 0) {
				startPolling();
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
			await loadMlOverview();
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
			await loadMlModels();
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
		<button class:active={activeTab === 'data'} onclick={() => (activeTab = 'data')}>Data</button>
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
						</div>
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

	<!-- Data Tab -->
	{:else if activeTab === 'data'}
		<div class="section">
			<div class="data-header">
				<h2>Signals v2.1 &mdash; Alpha Dataset</h2>
				<p class="data-sub">Released July 2025. Download via <code>numerapi</code> or the Numerai API.</p>
			</div>

			<div class="data-install">
				<code>pip install numerapi</code>
			</div>

			<div class="data-grid">
				{#each dataFiles as file}
					<div class="data-card">
						<div class="data-card-header">
							<span class="data-filename">{file.name}</span>
							<span class="data-badge" class:train={file.name.startsWith('train')} class:val={file.name.startsWith('validation')} class:live={file.name.startsWith('live')}>
								{file.name.startsWith('train') ? 'train' : file.name.startsWith('validation') ? 'validation' : 'live'}
							</span>
						</div>
						<p class="data-card-desc">{file.desc}</p>
						<code class="data-download">api.download_dataset("v2.1/{file.name}", "{file.name}")</code>
					</div>
				{/each}
			</div>

			<div class="data-snippet">
				<h3>Quick Start</h3>
				<pre><code>from numerapi import SignalsAPI{'\n'}api = SignalsAPI(){'\n'}{'\n'}# Download training data{'\n'}api.download_dataset("v2.1/train.parquet", "train.parquet"){'\n'}api.download_dataset("v2.1/train_neutralizer.parquet", "train_neutralizer.parquet"){'\n'}api.download_dataset("v2.1/train_sample_weights.parquet", "train_sample_weights.parquet"){'\n'}{'\n'}# Download validation data{'\n'}api.download_dataset("v2.1/validation.parquet", "validation.parquet"){'\n'}{'\n'}# Download live data for predictions{'\n'}api.download_dataset("v2.1/live.parquet", "live.parquet")</code></pre>
			</div>
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

	/* ── Data tab ── */
	.data-header { margin-bottom: 1rem; }
	.data-header h2 { margin-bottom: 0.25rem; }
	.data-sub {
		color: var(--text-secondary);
		font-size: 0.82rem;
		margin: 0;
	}
	.data-sub code {
		background: var(--bg-input);
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
		font-size: 0.78rem;
		color: var(--purple);
	}

	.data-install {
		background: var(--bg-card);
		border: 1px solid var(--border-light);
		border-radius: 8px;
		padding: 0.6rem 1rem;
		margin-bottom: 1rem;
		display: inline-block;
	}
	.data-install code {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.82rem;
		color: var(--text);
	}

	.data-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
		gap: 0.75rem;
		margin-bottom: 1.5rem;
	}

	.data-card {
		background: var(--bg-card);
		border: 1px solid var(--border-light);
		border-radius: 8px;
		padding: 0.85rem 1rem;
		box-shadow: var(--shadow-sm);
	}

	.data-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.35rem;
	}

	.data-filename {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--text);
	}

	.data-badge {
		font-size: 0.6rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 0.1rem 0.4rem;
		border-radius: 8px;
	}

	.data-badge.train { background: var(--badge-blue); color: var(--blue); }
	.data-badge.val { background: var(--badge-orange); color: var(--orange); }
	.data-badge.live { background: var(--badge-green); color: var(--green); }

	.data-card-desc {
		font-size: 0.75rem;
		color: var(--text-secondary);
		margin: 0 0 0.5rem 0;
		line-height: 1.4;
	}

	.data-download {
		display: block;
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.65rem;
		color: var(--text-muted);
		background: var(--bg-input);
		padding: 0.3rem 0.5rem;
		border-radius: 4px;
		overflow-x: auto;
		white-space: nowrap;
	}

	.data-snippet {
		background: var(--bg-card);
		border: 1px solid var(--border-light);
		border-radius: 8px;
		padding: 1rem 1.25rem;
		box-shadow: var(--shadow-sm);
	}

	.data-snippet h3 {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-secondary);
		margin: 0 0 0.75rem 0;
	}

	.data-snippet pre {
		margin: 0;
		overflow-x: auto;
	}

	.data-snippet code {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.75rem;
		line-height: 1.6;
		color: var(--text);
	}

	/* ── Deploy tab ── */
	.deploy-form { width: 100%; }

	.deploy-grid {
		display: grid;
		grid-template-columns: 1fr 300px;
		gap: 1rem;
		align-items: start;
	}

	.deploy-section {
		background: var(--bg-card);
		border: 1px solid var(--border-light);
		border-radius: 10px;
		padding: 1.25rem 1.5rem;
		box-shadow: var(--shadow-sm);
	}

	.deploy-main { margin-bottom: 0; }
	.deploy-sidebar { display: flex; flex-direction: column; gap: 1rem; }

	.deploy-form h2 {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-secondary);
		margin: 0 0 0.75rem 0;
		padding-bottom: 0.5rem;
		border-bottom: 1px solid var(--border-light);
	}

	.deploy-form h2:not(:first-child) {
		margin-top: 1.25rem;
	}

	.deploy-form label > span:first-child {
		display: block;
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--text-muted);
		margin-bottom: 0.3rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.deploy-form input[type="text"],
	.deploy-form input[type="number"],
	.deploy-form select {
		width: 100%;
		padding: 0.5rem 0.6rem;
		background: var(--bg-input);
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text);
		font-size: 0.82rem;
		font-family: 'SF Mono', 'Consolas', monospace;
		transition: border-color 0.15s;
		min-height: 2.5rem;
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
		gap: 0.75rem;
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
		padding: 0.75rem 2rem;
		border-radius: 8px;
		cursor: pointer;
		color: white;
		font-size: 0.85rem;
		font-weight: 700;
		transition: opacity 0.15s, box-shadow 0.15s, transform 0.1s;
		box-shadow: 0 2px 4px rgba(130, 80, 223, 0.25);
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		min-height: 2.75rem;
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
		.data-grid { grid-template-columns: 1fr; }
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
