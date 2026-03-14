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
		stopPolling
	} from '$lib/ml-stores';
	import MetricCard from '$lib/components/ml/MetricCard.svelte';
	import LossChart from '$lib/components/ml/LossChart.svelte';
	import ModelComparisonChart from '$lib/components/ml/ModelComparisonChart.svelte';
	import TrainConfigModal from '$lib/components/ml/TrainConfigModal.svelte';
	import TrainingProgress from '$lib/components/ml/TrainingProgress.svelte';

	let activeTab = $state<'overview' | 'experiments' | 'models' | 'rounds'>('overview');
	let loading = $state(false);
	let error = $state<string | null>(null);

	// Experiments tab state
	let expandedExp = $state<number | null>(null);
	let expRuns = $state<MlRunData[]>([]);
	let expRunsLoading = $state(false);

	// Overview tab state
	let selectedRunId = $state<number | null>(null);
	let epochMetrics = $state<MlEpochMetric[]>([]);

	// Training modal state
	let showTrainModal = $state(false);
	let trainLoading = $state(false);

	onMount(async () => {
		loading = true;
		try {
			await Promise.all([
				loadMlOverview(),
				mlExperiments.refresh(),
				loadMlModels(),
				loadMlRounds()
			]);
			// Auto-start polling if there are active runs
			if (($mlOverview?.active_runs ?? 0) > 0) {
				startPolling();
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load ML data';
			addToast(error!, 'error');
		} finally {
			loading = false;
		}
	});

	onDestroy(() => {
		stopPolling();
	});

	async function handleTrain(config: TrainRequest) {
		trainLoading = true;
		try {
			const result = await triggerTraining(config);
			showTrainModal = false;
			addToast(`Training started: Run #${result.run_id}`, 'success');
			await loadMlOverview();
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to start training', 'error');
		} finally {
			trainLoading = false;
		}
	}

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
		try {
			const res = await api.getMlRunMetrics(runId);
			epochMetrics = res.data;
		} catch {
			epochMetrics = [];
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
		<h1>Numerai ML</h1>
		<div class="header-actions">
			{#if loading}
				<span class="loading-indicator">Loading...</span>
			{/if}
			<button class="train-btn" onclick={() => (showTrainModal = true)}>Start Training</button>
		</div>
	</header>

	<TrainConfigModal
		open={showTrainModal}
		onclose={() => (showTrainModal = false)}
		onsubmit={handleTrain}
		loading={trainLoading}
	/>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<div class="tabs">
		<button class:active={activeTab === 'overview'} onclick={() => (activeTab = 'overview')}>Overview</button>
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
									<td class="dim">{run.started_at || '\u2014'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		{#if epochMetrics.length > 0}
			<div class="section">
				<h2>Loss Curve &mdash; Run #{selectedRunId}</h2>
				<LossChart metrics={epochMetrics} />
			</div>
		{/if}

	<!-- Experiments Tab -->
	{:else if activeTab === 'experiments'}
		<div class="section">
			{#if $mlExperiments.items.length === 0 && !$mlExperiments.loading}
				<p class="placeholder">No experiments yet. Training runs will appear here.</p>
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
				<p class="placeholder">No registered models. Promote a run to create one.</p>
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
				<p class="placeholder">No Numerai submissions yet. Round history will appear here.</p>
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

	.header-actions {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.train-btn {
		background: var(--blue);
		border: none;
		padding: 0.45rem 1rem;
		border-radius: 6px;
		cursor: pointer;
		color: white;
		font-size: 0.8rem;
		font-weight: 600;
		transition: opacity 0.15s;
	}

	.train-btn:hover { opacity: 0.85; }
	h2 { font-size: 1rem; margin: 0 0 0.75rem 0; color: var(--text); }

	.loading-indicator { color: var(--text-secondary); font-size: 0.8rem; }
	.error { color: var(--red); }

	.tabs {
		display: flex;
		gap: 0;
		margin-bottom: 1rem;
		border-bottom: 2px solid var(--border-light);
	}

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
	}

	.tabs button:hover { color: var(--text); }
	.tabs button.active {
		color: var(--blue);
		border-bottom-color: var(--blue);
	}

	.cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: 0.6rem;
		margin-bottom: 1rem;
	}

	.section { margin-bottom: 1.25rem; }
	.table-wrapper { overflow-x: auto; }

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

	@media (max-width: 900px) {
		.cards { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
	}
</style>
