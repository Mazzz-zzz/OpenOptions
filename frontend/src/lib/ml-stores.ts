import { writable, get } from 'svelte/store';
import {
	api,
	type MlOverview,
	type MlExperimentData,
	type MlModelData,
	type MlRoundData,
	type MlEnsembleData,
} from './api';

// ── Overview ────────────────────────────────────────────────────────

export const mlOverview = writable<MlOverview | null>(null);

export async function loadMlOverview() {
	const data = await api.getMlOverview();
	mlOverview.set(data);
}

// ── Experiments (cursor-paginated) ──────────────────────────────────

function createExperimentStore() {
	const store = writable<{
		items: MlExperimentData[];
		cursor: number | null;
		hasMore: boolean;
		loading: boolean;
	}>({
		items: [],
		cursor: null,
		hasMore: true,
		loading: false,
	});

	async function load(reset = false) {
		const state = get(store);
		if (state.loading) return;

		store.update((s) => ({ ...s, loading: true }));
		try {
			const cursor = reset ? undefined : state.cursor ?? undefined;
			const res = await api.getMlExperiments({ cursor, limit: 20 });
			store.update((s) => ({
				items: reset ? res.data : [...s.items, ...res.data],
				cursor: res.next_cursor,
				hasMore: !!res.next_cursor,
				loading: false,
			}));
		} catch {
			store.update((s) => ({ ...s, loading: false }));
		}
	}

	return {
		subscribe: store.subscribe,
		load,
		refresh: () => load(true),
	};
}

export const mlExperiments = createExperimentStore();

// ── Models ──────────────────────────────────────────────────────────

export const mlModels = writable<MlModelData[]>([]);

export async function loadMlModels() {
	const res = await api.getMlModels();
	mlModels.set(res.data);
}

// ── Rounds ──────────────────────────────────────────────────────────

export const mlRounds = writable<MlRoundData[]>([]);

export async function loadMlRounds() {
	const res = await api.getMlRounds();
	mlRounds.set(res.data);
}

// ── Ensemble ────────────────────────────────────────────────────────

export const mlEnsemble = writable<MlEnsembleData | null>(null);

export async function loadMlEnsemble() {
	const res = await api.getMlEnsemble();
	mlEnsemble.set(res.data);
}
