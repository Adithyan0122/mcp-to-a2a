'use client';

import useSWR from 'swr';
import { fetcher } from '@/lib/api';

export default function AgentsPage() {
    const { data, error, isLoading } = useSWR('/api/agents/health', fetcher, {
        refreshInterval: 15000,
    });

    const agents = data?.agents || {};
    const circuitBreakers = data?.circuit_breakers || [];

    const getStatusColor = (agent: any) => {
        if (!agent.reachable) return { bg: 'bg-[#fa5252]/10', border: 'border-[#fa5252]/30', dot: 'bg-[#fa5252]', label: 'OFFLINE', badge: 'badge-red' };
        if (agent.status === 'ok') return { bg: 'bg-[#40c057]/10', border: 'border-[#40c057]/30', dot: 'bg-[#40c057]', label: 'ONLINE', badge: 'badge-green' };
        return { bg: 'bg-[#fab005]/10', border: 'border-[#fab005]/30', dot: 'bg-[#fab005]', label: 'DEGRADED', badge: 'badge-yellow' };
    };

    const agentList = Object.values(agents) as any[];

    return (
        <div>
            <h1 className="text-2xl font-bold text-white mb-2">Agent Health</h1>
            <p className="text-sm text-[#8b8b96] mb-8">
                Status of all {agentList.length} agents — polled every 15s
            </p>

            {/* Agent Cards Grid */}
            {isLoading ? (
                <div className="grid grid-cols-3 gap-4">
                    {[1, 2, 3, 4, 5, 6].map(i => (
                        <div key={i} className="skeleton h-32 rounded-xl" />
                    ))}
                </div>
            ) : error ? (
                <div className="card text-center text-[#fa5252]">Failed to load agent health</div>
            ) : (
                <div className="grid grid-cols-3 gap-4 mb-8">
                    {agentList.map((agent: any) => {
                        const status = getStatusColor(agent);
                        return (
                            <div key={agent.name} className={`card ${status.bg} border ${status.border}`}>
                                <div className="flex items-center justify-between mb-3">
                                    <div className="flex items-center gap-2">
                                        <div className={`w-2.5 h-2.5 rounded-full ${status.dot} ${agent.reachable ? 'pulse-dot' : ''
                                            }`} />
                                        <h3 className="font-semibold text-white text-sm">{agent.name}</h3>
                                    </div>
                                    <span className={`badge ${status.badge}`}>{status.label}</span>
                                </div>
                                <div className="grid grid-cols-2 gap-2 text-xs">
                                    <div>
                                        <span className="text-[#8b8b96]">Latency</span>
                                        <p className="font-mono font-semibold text-white">{agent.latency_ms?.toFixed(0) || '—'}ms</p>
                                    </div>
                                    <div>
                                        <span className="text-[#8b8b96]">Version</span>
                                        <p className="font-mono font-semibold text-white">{agent.version || '—'}</p>
                                    </div>
                                    {agent.uptime_s && (
                                        <div>
                                            <span className="text-[#8b8b96]">Uptime</span>
                                            <p className="font-mono font-semibold text-white">
                                                {(agent.uptime_s / 60).toFixed(0)}m
                                            </p>
                                        </div>
                                    )}
                                    {agent.db_connected !== undefined && (
                                        <div>
                                            <span className="text-[#8b8b96]">Database</span>
                                            <p className={`font-semibold ${agent.db_connected ? 'text-[#40c057]' : 'text-[#fa5252]'}`}>
                                                {agent.db_connected ? 'Connected' : 'Down'}
                                            </p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Circuit Breakers */}
            <div className="card">
                <h3 className="text-sm font-semibold text-[#8b8b96] uppercase tracking-wider mb-4">
                    Circuit Breakers
                </h3>
                {circuitBreakers.length === 0 ? (
                    <p className="text-[#8b8b96] text-sm">No circuit breakers registered yet.</p>
                ) : (
                    <div className="grid grid-cols-2 gap-3">
                        {circuitBreakers.map((cb: any) => (
                            <div key={cb.name} className="flex items-center justify-between p-3 rounded-lg bg-[#111118]">
                                <div>
                                    <span className="text-sm font-medium text-white">{cb.name}</span>
                                    <p className="text-[10px] text-[#8b8b96]">
                                        Failures: {cb.failure_count}/{cb.failure_threshold}
                                    </p>
                                </div>
                                <span className={`badge ${cb.state === 'closed' ? 'badge-green'
                                        : cb.state === 'open' ? 'badge-red'
                                            : 'badge-yellow'
                                    }`}>
                                    {cb.state.toUpperCase()}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
