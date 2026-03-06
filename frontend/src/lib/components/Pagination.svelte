<script lang="ts">
	let { store }: { store: any } = $props();
	let loading = $state(false);

	async function loadMore() {
		loading = true;
		try {
			await store.load(false);
		} finally {
			loading = false;
		}
	}
</script>

{#if $store.hasMore && $store.items.length > 0}
	<div class="pagination">
		<button onclick={loadMore} disabled={loading} class="load-more">
			{loading ? 'Loading...' : 'Load More'}
		</button>
	</div>
{/if}

<style>
	.pagination {
		display: flex;
		justify-content: center;
		padding: 1rem 0;
	}

	.load-more {
		background: #21262d;
		color: #c9d1d9;
		border: 1px solid #30363d;
		padding: 0.5rem 1.5rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.875rem;
	}

	.load-more:hover:not(:disabled) {
		background: #30363d;
	}

	.load-more:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
</style>
