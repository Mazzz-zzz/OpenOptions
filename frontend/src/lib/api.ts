const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	const opts: RequestInit = {
		method,
		headers: { 'Content-Type': 'application/json' },
	};
	if (body) {
		opts.body = JSON.stringify(body);
	}

	const res = await fetch(`${API_URL}/api${path}`, opts);
	if (!res.ok) {
		const text = await res.text();
		throw new Error(`API ${method} ${path} failed: ${res.status} ${text}`);
	}
	return res.json();
}

export const api = {
	// Underlyings
	getUnderlyings() {
		return request<{ data: FetchedUnderlying[] }>('GET', '/underlyings');
	},

	// Fetch
	fetchChain(underlying: string, force = false) {
		const qs = force ? '?force=true' : '';
		return request<{ snapshots: number; alerts_raised: number }>('POST', `/fetch/${underlying}${qs}`);
	},

	// Alerts
	getAlerts(params?: { cursor?: number; limit?: number; signal_type?: string }) {
		const query = new URLSearchParams();
		if (params?.cursor) query.set('cursor', String(params.cursor));
		if (params?.limit) query.set('limit', String(params.limit));
		if (params?.signal_type) query.set('signal_type', params.signal_type);
		const qs = query.toString();
		return request<{ data: Alert[]; next_cursor: number | null }>('GET', `/alerts${qs ? `?${qs}` : ''}`);
	},

	dismissAlert(id: number) {
		return request<{ id: number; dismissed: boolean }>('POST', `/alerts/${id}/dismiss`);
	},

	// Contracts
	getContracts(params?: { underlying?: string; limit?: number }) {
		const query = new URLSearchParams();
		if (params?.underlying) query.set('underlying', params.underlying);
		if (params?.limit) query.set('limit', String(params.limit));
		const qs = query.toString();
		return request<{ data: Contract[]; total: number }>('GET', `/contracts${qs ? `?${qs}` : ''}`);
	},

	// Surface
	getSurface(underlying: string, optionType?: string) {
		const query = new URLSearchParams();
		if (optionType) query.set('option_type', optionType);
		const qs = query.toString();
		return request<SurfaceData>('GET', `/surface/${underlying}${qs ? `?${qs}` : ''}`);
	},

	// Snapshots
	getSnapshots(contractId: number, limit = 50) {
		return request<{ data: SnapshotData[] }>('GET', `/snapshots/${contractId}?limit=${limit}`);
	},

	// IV Analysis
	getIvAnalysis(underlying: string, lookbackDays = 30) {
		return request<IvAnalysisData>('GET', `/iv-analysis/${underlying}?lookback_days=${lookbackDays}`);
	},
};

// Types
export interface FetchedUnderlying {
	symbol: string;
	market: string;
	source: string;
	last_fetched_at: string | null;
	last_spot: number | null;
	last_snapshot_count: number;
	last_alert_count: number;
}

export interface Alert {
	id: number;
	signal_type: string;
	confidence: string | null;
	dismissed: boolean;
	created_at: string;
	snapshot_id: number;
	bid: number | null;
	ask: number | null;
	mid: number | null;
	market_iv: number | null;
	model_iv: number | null;
	vega: number | null;
	gamma: number | null;
	theta: number | null;
	deviation: number | null;
	net_edge: number | null;
	triggered_by: string | null;
	symbol: string;
	underlying: string;
	strike: number;
	expiry: string;
	option_type: string;
}

export interface Contract {
	id: number;
	symbol: string;
	underlying: string;
	market: string;
	source: string;
	strike: number;
	expiry: string;
	option_type: string;
}

export interface SurfaceData {
	x: number[];
	x_moneyness: number[];
	y: string[];
	z_market: (number | null)[][];
	z_model: (number | null)[][];
	points: SurfacePoint[];
	spot: number | null;
}

export interface SurfacePoint {
	symbol: string;
	strike: number;
	moneyness: number | null;
	expiry: string;
	option_type: string;
	bid: number | null;
	ask: number | null;
	mid: number | null;
	market_iv: number | null;
	model_iv: number | null;
	delta_market: number | null;
	delta_model: number | null;
	vega: number | null;
	gamma: number | null;
	theta: number | null;
	deviation: number | null;
	net_edge: number | null;
}

export interface SnapshotData {
	id: number;
	ts: string | null;
	bid: number | null;
	ask: number | null;
	mid: number | null;
	market_iv: number | null;
	model_iv: number | null;
	delta_market: number | null;
	delta_model: number | null;
	vega: number | null;
	gamma: number | null;
	theta: number | null;
	deviation: number | null;
	net_edge: number | null;
	triggered_by: string | null;
}

export interface IvAnalysisData {
	spot: number | null;
	term_structure: TermStructurePoint[];
	ts_slope: number | null;
	skew_by_expiry: SkewByExpiry[];
	smile: SmilePoint[];
	straddles: StraddleData[];
	put_call_summary: PutCallSummary | null;
	iv_rank: IvRankData | null;
	historical_iv: { ts: string; iv: number }[];
}

export interface TermStructurePoint {
	expiry: string;
	dte: number;
	atm_iv: number;
	atm_model_iv: number | null;
	atm_strike: number;
}

export interface SkewByExpiry {
	expiry: string;
	dte: number;
	atm_iv: number;
	put_25d_iv: number | null;
	call_25d_iv: number | null;
	put_10d_iv: number | null;
	call_10d_iv: number | null;
	risk_reversal: number | null;
	butterfly: number | null;
	avg_deviation: number | null;
	max_deviation: number | null;
	contracts_with_edge: number;
	total_contracts: number;
	total_vega: number;
}

export interface SmilePoint {
	expiry: string;
	dte: number;
	strike: number;
	moneyness: number;
	delta: number;
	option_type: string;
	market_iv: number;
	model_iv: number | null;
	deviation: number | null;
	net_edge: number | null;
	vega: number | null;
}

export interface StraddleData {
	expiry: string;
	dte: number;
	atm_strike: number;
	atm_iv: number;
	atm_model_iv: number | null;
	vol_premium: number | null;
	call_mid: number;
	put_mid: number;
	straddle_price: number;
	straddle_pct: number;
	breakeven_up: number;
	breakeven_down: number;
	total_spread: number;
	total_theta: number | null;
	total_vega: number | null;
	total_gamma: number | null;
	theta_vega_ratio: number | null;
	risk_reversal: number | null;
}

export interface PutCallSummary {
	avg_put_iv: number | null;
	avg_call_iv: number | null;
	put_call_iv_spread: number | null;
	total_put_vega: number;
	total_call_vega: number;
	put_count: number;
	call_count: number;
}

export interface IvRankData {
	current_iv: number | null;
	rank: number | null;
	percentile: number | null;
	high: number | null;
	low: number | null;
	lookback_days: number;
	data_points: number;
}
