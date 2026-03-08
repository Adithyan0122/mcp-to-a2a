'use client';

import useSWR from 'swr';
import { fetcher } from '@/lib/api';

export default function OrdersPage() {
    const { data, error, isLoading } = useSWR('/api/orders', fetcher, {
        refreshInterval: 10000,
    });

    const orders = data?.orders || [];

    const totalSpend = orders.reduce((sum: number, o: any) => sum + parseFloat(o.total_price || 0), 0);
    const avgDelivery = orders.length > 0
        ? orders.reduce((sum: number, o: any) => sum + o.delivery_days, 0) / orders.length
        : 0;

    return (
        <div>
            <h1 className="text-2xl font-bold text-white mb-2">Order History</h1>
            <p className="text-sm text-[#8b8b96] mb-8">All confirmed restock orders with AI reasoning</p>

            {/* Stats */}
            <div className="grid grid-cols-4 gap-4 mb-8">
                <div className="card">
                    <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Total Orders</p>
                    <p className="text-2xl font-bold text-white">{orders.length}</p>
                </div>
                <div className="card">
                    <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Total Spend</p>
                    <p className="text-2xl font-bold text-[#4c6ef5]">${totalSpend.toFixed(0)}</p>
                </div>
                <div className="card">
                    <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Avg Delivery</p>
                    <p className="text-2xl font-bold text-white">{avgDelivery.toFixed(1)} days</p>
                </div>
                <div className="card">
                    <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Suppliers Used</p>
                    <p className="text-2xl font-bold text-[#7950f2]">
                        {new Set(orders.map((o: any) => o.supplier)).size}
                    </p>
                </div>
            </div>

            {/* Orders Table */}
            <div className="card p-0 overflow-hidden">
                {isLoading ? (
                    <div className="p-8 text-center text-[#8b8b96]">Loading orders...</div>
                ) : error ? (
                    <div className="p-8 text-center text-[#fa5252]">Failed to load orders</div>
                ) : orders.length === 0 ? (
                    <div className="p-8 text-center text-[#8b8b96]">No orders yet. Trigger a pipeline run!</div>
                ) : (
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Product</th>
                                <th>Qty</th>
                                <th>Supplier</th>
                                <th>Unit Price</th>
                                <th>Total</th>
                                <th>Delivery</th>
                                <th>Score</th>
                                <th>Status</th>
                                <th>Date</th>
                            </tr>
                        </thead>
                        <tbody>
                            {orders.map((order: any) => (
                                <tr key={order.id}>
                                    <td className="font-mono text-[#4c6ef5]">#{order.id}</td>
                                    <td className="font-medium text-white">{order.product}</td>
                                    <td className="font-mono">{order.quantity}</td>
                                    <td>
                                        <span className="badge badge-blue">{order.supplier}</span>
                                    </td>
                                    <td className="font-mono">${parseFloat(order.unit_price).toFixed(2)}</td>
                                    <td className="font-mono font-semibold text-white">
                                        ${parseFloat(order.total_price).toFixed(2)}
                                    </td>
                                    <td>{order.delivery_days}d</td>
                                    <td className="font-mono text-[#8b8b96]">{parseFloat(order.score).toFixed(4)}</td>
                                    <td>
                                        <span className="badge badge-green">{order.status}</span>
                                    </td>
                                    <td className="text-[#8b8b96] text-xs">
                                        {new Date(order.created_at).toLocaleDateString()}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
