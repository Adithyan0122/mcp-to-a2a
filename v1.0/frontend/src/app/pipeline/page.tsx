'use client';

import { useState, useEffect, useRef } from 'react';
import { createWebSocket } from '@/lib/api';
import useSWR from 'swr';
import { fetcher } from '@/lib/api';

type PipelineEvent = {
    step: string;
    status: string;
    ms?: number;
    updates?: number;
    product?: string;
    supplier?: string;
    order_id?: number;
    pipeline_id?: string;
    error?: string;
    timestamp?: number;
};

const AGENT_NODES = [
    { id: 'price_sync', label: 'Price Sync', icon: '💲', x: 1, y: 0 },
    { id: 'inventory_check', label: 'Inventory', icon: '📦', x: 2, y: 0 },
    { id: 'low_stock_detected', label: 'Low Stock', icon: '⚠️', x: 3, y: 0 },
    { id: 'supplier_bidding', label: 'Bidding', icon: '🏷️', x: 4, y: 0 },
    { id: 'finance_approval', label: 'Finance', icon: '💰', x: 5, y: 0 },
    { id: 'order_confirmed', label: 'Order', icon: '✅', x: 6, y: 0 },
    { id: 'notification', label: 'Notify', icon: '📧', x: 7, y: 0 },
];

export default function PipelinePage() {
    const [events, setEvents] = useState<PipelineEvent[]>([]);
    const [activeSteps, setActiveSteps] = useState<Set<string>>(new Set());
    const [completedSteps, setCompletedSteps] = useState<Set<string>>(new Set());
    const wsRef = useRef<WebSocket | null>(null);

    const { data: eventsData } = useSWR('/api/pipeline/events?limit=30', fetcher, {
        refreshInterval: 10000,
    });

    useEffect(() => {
        const ws = createWebSocket('/ws/pipeline');
        wsRef.current = ws;

        ws.onmessage = (msg) => {
            try {
                const event: PipelineEvent = JSON.parse(msg.data);
                event.timestamp = Date.now();
                setEvents(prev => [event, ...prev].slice(0, 50));

                if (event.status === 'started') {
                    setActiveSteps(prev => new Set(prev).add(event.step));
                } else if (event.status === 'complete') {
                    setActiveSteps(prev => { const n = new Set(prev); n.delete(event.step); return n; });
                    setCompletedSteps(prev => new Set(prev).add(event.step));
                }

                if (event.step === 'pipeline' && event.status === 'complete') {
                    setTimeout(() => {
                        setActiveSteps(new Set());
                        setCompletedSteps(new Set());
                    }, 5000);
                }
            } catch { }
        };

        ws.onerror = () => { };
        ws.onclose = () => { };

        return () => ws.close();
    }, []);

    const recentEvents = eventsData?.events || [];

    return (
        <div>
            <h1 className="text-2xl font-bold text-white mb-2">Live Pipeline</h1>
            <p className="text-sm text-[#8b8b96] mb-8">Real-time visualization of the AI supply chain pipeline</p>

            {/* Pipeline Node Visualization */}
            <div className="card mb-8">
                <h3 className="text-sm font-semibold text-[#8b8b96] uppercase tracking-wider mb-6">Pipeline Flow</h3>
                <div className="flex items-center justify-between px-4">
                    {AGENT_NODES.map((node, i) => {
                        const isActive = activeSteps.has(node.id);
                        const isComplete = completedSteps.has(node.id);

                        return (
                            <div key={node.id} className="flex items-center">
                                <div className={`flex flex-col items-center transition-all duration-300 ${isActive ? 'scale-110' : ''
                                    }`}>
                                    <div className={`w-14 h-14 rounded-xl flex items-center justify-center text-2xl
                    border transition-all duration-300 ${isActive
                                            ? 'border-[#4c6ef5] bg-[#4c6ef5]/20 glow-blue'
                                            : isComplete
                                                ? 'border-[#40c057] bg-[#40c057]/10 glow-green'
                                                : 'border-[#2a2a35] bg-[#16161d]'
                                        }`}>
                                        {node.icon}
                                    </div>
                                    <span className={`mt-2 text-xs font-medium ${isActive ? 'text-[#4c6ef5]' : isComplete ? 'text-[#40c057]' : 'text-[#8b8b96]'
                                        }`}>
                                        {node.label}
                                    </span>
                                    {isActive && (
                                        <span className="mt-1 text-[10px] text-[#4c6ef5] animate-pulse">RUNNING</span>
                                    )}
                                </div>
                                {i < AGENT_NODES.length - 1 && (
                                    <div className={`w-8 h-0.5 mx-2 transition-colors duration-300 ${isComplete ? 'bg-[#40c057]' : 'bg-[#2a2a35]'
                                        }`} />
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Live Event Feed */}
            <div className="grid grid-cols-2 gap-6">
                <div className="card">
                    <h3 className="text-sm font-semibold text-[#8b8b96] uppercase tracking-wider mb-4">
                        Live Events (WebSocket)
                    </h3>
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                        {events.length === 0 ? (
                            <p className="text-[#8b8b96] text-sm">Waiting for pipeline events... Trigger a pipeline run.</p>
                        ) : (
                            events.map((event, i) => (
                                <div key={i} className="flex items-start gap-3 p-2 rounded-lg bg-[#111118]">
                                    <span className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${event.status === 'complete' ? 'bg-[#40c057]'
                                            : event.status === 'started' ? 'bg-[#4c6ef5] animate-pulse'
                                                : event.status === 'error' ? 'bg-[#fa5252]'
                                                    : 'bg-[#8b8b96]'
                                        }`} />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                            <span className="text-xs font-semibold text-white">{event.step}</span>
                                            <span className={`badge text-[10px] ${event.status === 'complete' ? 'badge-green'
                                                    : event.status === 'started' ? 'badge-blue'
                                                        : 'badge-red'
                                                }`}>{event.status}</span>
                                        </div>
                                        {event.ms && (
                                            <span className="text-[10px] text-[#8b8b96] font-mono">{event.ms}ms</span>
                                        )}
                                        {event.product && (
                                            <span className="text-[10px] text-[#8b8b96] ml-2">{event.product}</span>
                                        )}
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>

                <div className="card">
                    <h3 className="text-sm font-semibold text-[#8b8b96] uppercase tracking-wider mb-4">
                        Recent Runs
                    </h3>
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                        {recentEvents.length === 0 ? (
                            <p className="text-[#8b8b96] text-sm">No recent pipeline events.</p>
                        ) : (
                            recentEvents.map((event: any, i: number) => (
                                <div key={i} className="flex items-center gap-3 p-2 rounded-lg bg-[#111118] text-sm">
                                    <span className={`w-2 h-2 rounded-full ${event.status === 'complete' ? 'bg-[#40c057]' : 'bg-[#fa5252]'
                                        }`} />
                                    <span className="text-white font-medium">{event.step}</span>
                                    <span className="text-[#8b8b96] text-xs ml-auto font-mono">{event.ms || '—'}ms</span>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
