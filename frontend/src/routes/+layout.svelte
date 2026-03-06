<script>
	let { children } = $props();
</script>

<div class="app">
	<nav>
		<div class="nav-brand" title="OpenOptions — Options mispricing detection platform">OpenOptions</div>
		<div class="nav-links">
			<a href="/" title="Mispricing alerts — options where market IV deviates from the model, sorted by net edge">Dashboard</a>
			<a href="/surface" title="3D volatility surface — visualize market vs model IV across strikes and expiries">Vol Surface</a>
			<a href="/iv-crush" title="IV crush analysis — term structure, IV rank, ATM straddle pricing for short vol strategies">IV Crush</a>
			<a href="/contracts" title="Browse all tracked option contracts — filter, sort, and manage your watchlist">Contracts</a>
		</div>
	</nav>

	<main>
		{@render children()}
	</main>
</div>

<style>
	:global(body) {
		margin: 0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		background: #0f1117;
		color: #e1e4e8;
	}

	.app {
		min-height: 100vh;
	}

	nav {
		display: flex;
		align-items: center;
		gap: 2rem;
		padding: 0.75rem 1.5rem;
		background: #161b22;
		border-bottom: 1px solid #30363d;
	}

	.nav-brand {
		font-size: 1.25rem;
		font-weight: 700;
		color: #58a6ff;
	}

	.nav-links {
		display: flex;
		gap: 1rem;
	}

	.nav-links a {
		color: #8b949e;
		text-decoration: none;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
		transition: color 0.15s;
	}

	.nav-links a:hover {
		color: #e1e4e8;
	}

	main {
		max-width: 1200px;
		margin: 0 auto;
		padding: 1.5rem;
	}
</style>
