<script lang="ts">
	import { api, type TrackedUnderlying } from '$lib/api';

	let {
		onselect,
	}: {
		onselect?: (symbol: string) => void;
	} = $props();

	let items = $state<TrackedUnderlying[]>([]);
	let loading = $state(true);

	export async function refresh() {
		try {
			const res = await api.getUnderlyings();
			items = res.data;
		} catch {
			// silent
		} finally {
			loading = false;
		}
	}

	refresh();

	async function remove(symbol: string) {
		try {
			await api.removeUnderlying(symbol);
			items = items.filter(i => i.symbol !== symbol);
		} catch {
			// silent
		}
	}

	function timeAgo(iso: string | null): string {
		if (!iso) return '';
		const diff = Date.now() - new Date(iso).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		return `${Math.floor(hrs / 24)}d ago`;
	}
</script>

{#if loading}
	<div class="tracked-bar placeholder">Loading tracked symbols...</div>
{:else if items.length > 0}
	<div class="tracked-bar">
		<span class="label">Tracked</span>
		{#each items as item}
			<div
				class="chip"
				class:cooldown={item.on_cooldown}
				role="button"
				tabindex="0"
				onclick={() => onselect?.(item.symbol)}
				onkeydown={(e) => { if (e.key === 'Enter') onselect?.(item.symbol); }}
				title={item.last_spot ? `$${item.last_spot.toLocaleString()}` : ''}
			>
				<span class="chip-symbol">{item.symbol}</span>
				<span class="chip-meta">
					{item.last_snapshot_count}c / {item.last_alert_count}a
				</span>
				{#if item.last_fetched_at}
					<span class="chip-time">{timeAgo(item.last_fetched_at)}</span>
				{/if}
				{#if item.on_cooldown}
					<span class="chip-cooldown" title="Cooldown active">&#9202;</span>
				{/if}
				<button
					class="chip-remove"
					onclick={(e) => { e.stopPropagation(); remove(item.symbol); }}
					title="Stop tracking"
				>
					&times;
				</button>
			</div>
		{/each}
	</div>
{/if}

<style>
	.tracked-bar {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex-wrap: wrap;
		padding: 0.5rem 0;
		margin-bottom: 0.75rem;
		border-bottom: 1px solid #21262d;
	}

	.tracked-bar.placeholder {
		color: #484f58;
		font-size: 0.8rem;
	}

	.label {
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #484f58;
		font-weight: 600;
		margin-right: 0.25rem;
	}

	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		background: #21262d;
		border: 1px solid #30363d;
		border-radius: 16px;
		padding: 0.2rem 0.5rem;
		cursor: pointer;
		font-family: inherit;
		font-size: 0.75rem;
		color: #c9d1d9;
		transition: border-color 0.15s, background 0.15s;
	}

	.chip:hover {
		border-color: #58a6ff;
		background: #161b22;
	}

	.chip.cooldown {
		opacity: 0.6;
	}

	.chip-symbol {
		font-weight: 600;
		color: #e1e4e8;
	}

	.chip-meta {
		color: #8b949e;
		font-size: 0.65rem;
	}

	.chip-time {
		color: #484f58;
		font-size: 0.65rem;
	}

	.chip-cooldown {
		font-size: 0.65rem;
	}

	.chip-remove {
		background: none;
		border: none;
		color: #484f58;
		cursor: pointer;
		padding: 0 2px;
		font-size: 0.85rem;
		line-height: 1;
	}

	.chip-remove:hover {
		color: #f85149;
	}
</style>
