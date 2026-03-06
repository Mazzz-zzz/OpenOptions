<script lang="ts">
	import { api, type Contract } from '$lib/api';
	import { loadContracts } from '$lib/stores';

	let { contract }: { contract: Contract } = $props();
	let toggling = $state(false);

	async function toggleWatch() {
		toggling = true;
		try {
			if (contract.is_watchlisted) {
				await api.unwatchContract(contract.id);
			} else {
				await api.watchContract(contract.id);
			}
			await loadContracts();
		} finally {
			toggling = false;
		}
	}
</script>

<tr>
	<td class="mono">{contract.symbol}</td>
	<td>{contract.underlying}</td>
	<td class="num">{contract.strike.toLocaleString()}</td>
	<td>{contract.expiry}</td>
	<td>{contract.option_type}</td>
	<td>{contract.source}</td>
	<td>
		<button class="watch-btn" class:watched={contract.is_watchlisted} onclick={toggleWatch} disabled={toggling}>
			{contract.is_watchlisted ? 'Unwatch' : 'Watch'}
		</button>
	</td>
</tr>

<style>
	td {
		padding: 0.4rem 0.75rem;
		border-bottom: 1px solid #21262d;
	}

	.mono {
		font-family: 'SF Mono', monospace;
		font-size: 0.8rem;
	}

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.watch-btn {
		background: none;
		border: 1px solid #30363d;
		color: #8b949e;
		padding: 0.2rem 0.6rem;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.75rem;
	}

	.watch-btn:hover:not(:disabled) {
		border-color: #58a6ff;
		color: #58a6ff;
	}

	.watch-btn.watched {
		border-color: #238636;
		color: #3fb950;
	}

	.watch-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
