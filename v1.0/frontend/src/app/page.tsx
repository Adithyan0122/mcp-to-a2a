'use client';

import { useState, useEffect } from 'react';
import useSWR from 'swr';
import { fetcher, postApi } from '@/lib/api';

export default function InventoryPage() {
    const { data, error, isLoading, mutate } = useSWR('/api/inventory', fetcher, {
        refreshInterval: 5000,
    });
    const { data: marketData } = useSWR('/api/market/prices', fetcher, {
        refreshInterval: 5000,
    });

    const [triggering, setTriggering] = useState(false);

    const triggerPipeline = async () => {
        setTriggering(true);
        try {
            await postApi('/api/pipeline/trigger');
            setTimeout(() => mutate(), 3000);
        } finally {
            setTriggering(false);
        }
    };

    const products = data?.products || [];
    const marketPrices = marketData?.prices || {};

    const getStockStatus = (qty: number) => {
        if (qty < 10) return { label: 'CRITICAL', class: 'badge-red', glow: 'glow-red' };
        if (qty < 15) return { label: 'LOW', class: 'badge-yellow', glow: 'glow-yellow' };
        return { label: 'HEALTHY', class: 'badge-green', glow: 'glow-green' };
    };

    return (
        <div>
            {/* Header */}
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h1 className="text-2xl font-bold text-white">Live Inventory</h1>
                    <p className="text-sm text-[#8b8b96] mt-1">Real-time stock levels with AI-powered restocking</p>
                </div>
                <button
                    onClick={triggerPipeline}
                    disabled={triggering}
                    className="px-5 py-2.5 rounded-lg text-sm font-semibold text-white transition-all duration-200 disabled:opacity-50"
                    style={{ background: 'linear-gradient(135deg, #4c6ef5, #7950f2)' }}
                >
                    {triggering ? '⏳ Running Pipeline...' : '⚡ Trigger Pipeline'}
                </button>
            </div>

            {/* Stats Row */}
            <div className="grid grid-cols-4 gap-4 mb-8">
                <div className="card">
                    <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Total Products</p>
                    <p className="text-2xl font-bold text-white">{products.length}</p>
                </div>
                <div className="card">
                    <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Low Stock</p>
                    <p className="text-2xl font-bold text-[#fa5252]">
                        {products.filter((p: any) => p.quantity < 15).length}
                    </p>
                </div>
                <div className="card">
                    <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Total Units</p>
                    <p className="text-2xl font-bold text-white">
                        {products.reduce((sum: number, p: any) => sum + p.quantity, 0)}
                    </p>
                </div>
                <div className="card">
                    <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Total Value</p>
                    <p className="text-2xl font-bold text-[#40c057]">
                        ${products.reduce((sum: number, p: any) => sum + p.quantity * parseFloat(p.price), 0).toFixed(0)}
                    </p>
                </div>
            </div>

            {/* Inventory Table */}
            <div className="card p-0 overflow-hidden">
                {isLoading ? (
                    <div className="p-8 text-center text-[#8b8b96]">Loading inventory...</div>
                ) : error ? (
                    <div className="p-8 text-center text-[#fa5252]">Failed to load inventory</div>
                ) : (
                    <table>
                        <thead>
                            <tr>
                                <th>Product</th>
                                <th>Quantity</th>
                                <th>Status</th>
                                <th>DB Price</th>
                                <th>Market Price</th>
                                <th>Drift</th>
                                <th>Last Updated</th>
                            </tr>
                        </thead>
                        <tbody>
                            {products.map((product: any) => {
                                const status = getStockStatus(product.quantity);
                                const dbPrice = parseFloat(product.price);
                                const mktPrice = marketPrices[product.product] || dbPrice;
                                const drift = dbPrice > 0 ? ((mktPrice - dbPrice) / dbPrice * 100) : 0;

                                return (
                                    <tr key={product.id}>
                                        <td className="font-medium text-white">{product.product}</td>
                                        <td>
                                            <span className="font-mono font-semibold">{product.quantity}</span>
                                        </td>
                                        <td>
                                            <span className={`badge ${status.class}`}>
                                                <span className="w-1.5 h-1.5 rounded-full bg-current" />
                                                {status.label}
                                            </span>
                                        </td>
                                        <td className="font-mono">${dbPrice.toFixed(2)}</td>
                                        <td className="font-mono">${mktPrice.toFixed(2)}</td>
                                        <td>
                                            <span className={`font-mono text-sm ${drift > 0 ? 'text-[#40c057]' : drift < 0 ? 'text-[#fa5252]' : 'text-[#8b8b96]'
                                                }`}>
                                                {drift > 0 ? '+' : ''}{drift.toFixed(1)}%
                                            </span>
                                        </td>
                                        <td className="text-[#8b8b96] text-xs">
                                            {new Date(product.updated_at).toLocaleTimeString()}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
