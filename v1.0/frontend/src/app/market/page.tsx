'use client';

import { useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '@/lib/api';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const PRODUCTS = ['Laptop', 'Mouse', 'Keyboard', 'Monitor', 'Webcam'];
const COLORS: Record<string, string> = {
    Laptop: '#4c6ef5', Mouse: '#40c057', Keyboard: '#fab005', Monitor: '#fa5252', Webcam: '#7950f2',
};

export default function MarketPage() {
    const [selectedProduct, setSelectedProduct] = useState('Laptop');

    const { data: marketData } = useSWR('/api/market/prices', fetcher, {
        refreshInterval: 3000,
    });

    const { data: historyData } = useSWR(
        `/api/market/history/${selectedProduct}?limit=100`,
        fetcher,
        { refreshInterval: 5000 }
    );

    const prices = marketData?.prices || {};
    const basePrices = marketData?.base || {};
    const history = historyData?.history || [];

    const chartData = history.map((h: any, i: number) => ({
        tick: h.tick || i,
        price: h.price,
        base: basePrices[selectedProduct] || 0,
    }));

    return (
        <div>
            <h1 className="text-2xl font-bold text-white mb-2">Market Prices</h1>
            <p className="text-sm text-[#8b8b96] mb-8">Live market price simulation with history charts</p>

            {/* Current Prices */}
            <div className="grid grid-cols-5 gap-4 mb-8">
                {PRODUCTS.map(product => {
                    const current = prices[product] || 0;
                    const base = basePrices[product] || 1;
                    const drift = ((current - base) / base * 100);
                    const isSelected = product === selectedProduct;

                    return (
                        <button
                            key={product}
                            onClick={() => setSelectedProduct(product)}
                            className={`card text-left cursor-pointer transition-all duration-200 ${isSelected ? 'border-[#4c6ef5]/50 bg-[#4c6ef5]/5' : ''
                                }`}
                        >
                            <p className="text-xs text-[#8b8b96] mb-1">{product}</p>
                            <p className="text-xl font-bold font-mono text-white">${current.toFixed(2)}</p>
                            <p className={`text-xs font-mono mt-1 ${drift > 0 ? 'text-[#40c057]' : drift < 0 ? 'text-[#fa5252]' : 'text-[#8b8b96]'
                                }`}>
                                {drift > 0 ? '▲' : drift < 0 ? '▼' : '—'} {Math.abs(drift).toFixed(2)}%
                            </p>
                        </button>
                    );
                })}
            </div>

            {/* Price Chart */}
            <div className="card mb-8">
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-[#8b8b96] uppercase tracking-wider">
                        {selectedProduct} — Price History (Last 100 Ticks)
                    </h3>
                    <div className="flex items-center gap-2">
                        <div className="w-3 h-0.5 rounded" style={{ backgroundColor: COLORS[selectedProduct] }} />
                        <span className="text-xs text-[#8b8b96]">Market</span>
                        <div className="w-3 h-0.5 rounded bg-[#8b8b96] ml-3" />
                        <span className="text-xs text-[#8b8b96]">Base</span>
                    </div>
                </div>
                <ResponsiveContainer width="100%" height={350}>
                    <LineChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#2a2a35" />
                        <XAxis dataKey="tick" stroke="#8b8b96" fontSize={10} />
                        <YAxis stroke="#8b8b96" fontSize={10} domain={['auto', 'auto']} />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: '#16161d',
                                border: '1px solid #2a2a35',
                                borderRadius: '8px',
                                fontSize: '12px',
                            }}
                        />
                        <Line
                            type="monotone"
                            dataKey="price"
                            stroke={COLORS[selectedProduct]}
                            strokeWidth={2}
                            dot={false}
                            name="Market Price"
                        />
                        <Line
                            type="monotone"
                            dataKey="base"
                            stroke="#8b8b96"
                            strokeWidth={1}
                            strokeDasharray="5 5"
                            dot={false}
                            name="Base Price"
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>

            {/* All Prices Table */}
            <div className="card p-0 overflow-hidden">
                <table>
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Market Price</th>
                            <th>Base Price</th>
                            <th>Drift</th>
                            <th>Direction</th>
                        </tr>
                    </thead>
                    <tbody>
                        {PRODUCTS.map(product => {
                            const current = prices[product] || 0;
                            const base = basePrices[product] || 1;
                            const drift = ((current - base) / base * 100);
                            return (
                                <tr key={product} className="cursor-pointer" onClick={() => setSelectedProduct(product)}>
                                    <td className="font-medium text-white">
                                        <span className="inline-block w-2 h-2 rounded-full mr-2"
                                            style={{ backgroundColor: COLORS[product] }} />
                                        {product}
                                    </td>
                                    <td className="font-mono">${current.toFixed(2)}</td>
                                    <td className="font-mono text-[#8b8b96]">${base.toFixed(2)}</td>
                                    <td className={`font-mono ${drift > 0 ? 'text-[#40c057]' : drift < 0 ? 'text-[#fa5252]' : ''}`}>
                                        {drift > 0 ? '+' : ''}{drift.toFixed(2)}%
                                    </td>
                                    <td className="text-lg">
                                        {drift > 2 ? '📈' : drift < -2 ? '📉' : '➡️'}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
