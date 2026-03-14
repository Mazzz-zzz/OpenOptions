<script lang="ts">
	import type { TrainRequest } from '$lib/api';

	interface Props {
		open: boolean;
		onclose: () => void;
		onsubmit: (config: TrainRequest) => void;
		loading?: boolean;
	}

	let { open, onclose, onsubmit, loading = false }: Props = $props();

	let experimentName = $state('');
	let description = $state('');
	let featureSet = $state('medium');
	let modelType = $state('lgbm');
	let instanceType = $state('ml.m5.xlarge');
	let uploadToNumerai = $state(false);
	let showAdvanced = $state(false);
	let hyperparamsText = $state('');
	// NEW: Model configuration options
	let neutralizationPct = $state(50);

	function handleSubmit() {
		if (!experimentName.trim()) return;

		const config: TrainRequest = {
			experiment_name: experimentName.trim(),
			feature_set: featureSet,
			model_type: modelType,
			instance_type: instanceType,
			neutralization_pct: neutralizationPct,
		};

		if (description.trim()) {
			config.description = description.trim();
		}

		if (uploadToNumerai) {
			config.upload = true;
		}

		if (hyperparamsText.trim()) {
			try {
				config.hyperparams = JSON.parse(hyperparamsText);
			} catch {
				return; // invalid JSON, don't submit
			}
		}

		onsubmit(config);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div class="modal-overlay" role="dialog" aria-modal="true" onkeydown={handleKeydown}>
		<div class="modal">
			<header>
				<h2>Start Training</h2>
				<button class="close-btn" onclick={onclose}>&times;</button>
			</header>

			<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
				<label>
					<span>Experiment Name</span>
					<input type="text" bind:value={experimentName} placeholder="e.g. baseline-v2" required />
				</label>

				<label>
					<span>Description</span>
					<input type="text" bind:value={description} placeholder="Optional description" />
				</label>

				<div class="row">
					<label>
						<span>Feature Set</span>
						<select bind:value={featureSet}>
							<option value="small">Small (42)</option>
							<option value="medium">Medium (705)</option>
							<option value="all">All (2376)</option>
						</select>
					</label>

					<label>
						<span>Model Type</span>
						<select bind:value={modelType}>
							<option value="lgbm">LightGBM</option>
							<option value="catboost">CatBoost</option>
						</select>
					</label>
				</div>

				<label>
					<span>Instance Type</span>
					<select bind:value={instanceType}>
						<option value="ml.m5.xlarge">ml.m5.xlarge (4 vCPU, 16 GB)</option>
						<option value="ml.m5.2xlarge">ml.m5.2xlarge (8 vCPU, 32 GB)</option>
					</select>
				</label>

				<label>
					<span>Feature Neutralization ({neutralizationPct}%)</span>
					<input 
						type="range" 
						bind:value={neutralizationPct} 
						min="0" 
						max="100" 
						step="5"
					/>
				</label>

				<label class="checkbox-label">
					<input type="checkbox" bind:checked={uploadToNumerai} />
					<span class="checkbox-text">Upload to Numerai after training</span>
				</label>

				<button type="button" class="advanced-toggle" onclick={() => (showAdvanced = !showAdvanced)}>
					{showAdvanced ? '\u25BC' : '\u25B6'} Advanced: Hyperparameters
				</button>

				{#if showAdvanced}
					<label>
						<span>Hyperparameters (JSON)</span>
						<textarea bind:value={hyperparamsText} placeholder={'{"num_leaves": 512, "learning_rate": 0.005}'} rows="4"></textarea>
					</label>
				{/if}

				<div class="actions">
					<button type="button" class="cancel-btn" onclick={onclose}>Cancel</button>
					<button type="submit" class="submit-btn" disabled={!experimentName.trim() || loading}>
						{loading ? 'Starting...' : 'Start Training'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<style>
	.modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.modal {
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 12px;
		padding: 1.5rem;
		width: 100%;
		max-width: 480px;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1.25rem;
	}

	h2 {
		font-size: 1.1rem;
		margin: 0;
	}

	.close-btn {
		background: none;
		border: none;
		font-size: 1.5rem;
		cursor: pointer;
		color: var(--text-muted);
		padding: 0;
		line-height: 1;
	}

	label {
		display: block;
		margin-bottom: 0.75rem;
	}

	label span {
		display: block;
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--text-secondary);
		margin-bottom: 0.25rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	input,
	select,
	textarea {
		width: 100%;
		padding: 0.5rem 0.6rem;
		background: var(--bg-input);
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text);
		font-size: 0.85rem;
		font-family: inherit;
	}

	textarea {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.78rem;
		resize: vertical;
	}

	input:focus,
	select:focus,
	textarea:focus {
		outline: none;
		border-color: var(--blue);
	}

	.row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.75rem;
	}

	.checkbox-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
		cursor: pointer;
	}

	.checkbox-label input[type='checkbox'] {
		width: auto;
		margin: 0;
		accent-color: var(--blue);
	}

	.checkbox-text {
		font-size: 0.85rem;
		color: var(--text-secondary);
		text-transform: none;
		letter-spacing: normal;
		font-weight: normal;
	}

	.advanced-toggle {
		background: none;
		border: none;
		color: var(--text-secondary);
		font-size: 0.8rem;
		cursor: pointer;
		padding: 0.25rem 0;
		margin-bottom: 0.5rem;
	}

	.advanced-toggle:hover {
		color: var(--text);
	}

	.actions {
		display: flex;
		gap: 0.5rem;
		justify-content: flex-end;
		margin-top: 1rem;
	}

	.cancel-btn {
		background: var(--bg-input);
		border: 1px solid var(--border);
		padding: 0.5rem 1rem;
		border-radius: 6px;
		cursor: pointer;
		color: var(--text-secondary);
		font-size: 0.85rem;
	}

	.submit-btn {
		background: var(--blue);
		border: none;
		padding: 0.5rem 1.25rem;
		border-radius: 6px;
		cursor: pointer;
		color: white;
		font-size: 0.85rem;
		font-weight: 600;
	}

	.submit-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.submit-btn:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
