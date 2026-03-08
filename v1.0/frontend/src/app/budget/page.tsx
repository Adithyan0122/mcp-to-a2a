'use client';

import useSWR from 'swr';
import { fetcher } from '@/lib/api';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';

export default function BudgetPage() {
    const { data: budgetData, isLoading: budgetLoading } = useSWR('/api/budget', fetcher, {
        refreshInterval: 10000,
    });
    const { data: txnData } = useSWR('/api/budget/transactions', fetcher, {
        refreshInterval: 10000,
    });

    const budget = budgetData || {};
    const transactions = txnData?.transactions || [];
    const total = budget.total_budget || 50000;
    const spent = budget.spent || 0;
    const remaining = budget.remaining || total;
    const pct = budget.utilization_pct || 0;

    const donutData = [
        { name: 'Spent', value: spent, color: '#4c6ef5' },
        { name: 'Remaining', value: remaining, color: '#2a2a35' },
    ];

    return (
        <div>
            <h1 className="text-2xl font-bold text-white mb-2">Finance Overview</h1>
            <p className="text-sm text-[#8b8b96] mb-8">
                Monthly budget: {budget.month || '—'} — AI-powered spend approval
            </p>

            {/* Budget Overview */}
            <div className="grid grid-cols-3 gap-6 mb-8">
                {/* Donut Chart */}
                <div className="card col-span-1 flex flex-col items-center justify-center">
                    <div className="relative w-48 h-48">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={donutData}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={55}
                                    outerRadius={75}
                                    startAngle={90}
                                    endAngle={-270}
                                    dataKey="value"
                                    stroke="none"
                                >
                                    {donutData.map((entry, i) => (
                                        <Cell key={i} fill={entry.color} />
                                    ))}
                                </Pie>
                                <Tooltip
                                    contentStyle={{
                                        backgroundColor: '#16161d',
                                        border: '1px solid #2a2a35',
                                        borderRadius: '8px',
                                        fontSize: '12px',
                                    }}
                                    formatter={(value: number) => `$${value.toFixed(2)}`}
                                />
                            </PieChart>
                        </ResponsiveContainer>
                        <div className="absolute inset-0 flex flex-col items-center justify-center">
                            <span className="text-2xl font-bold text-white">{pct.toFixed(0)}%</span>
                            <span className="text-[10px] text-[#8b8b96] uppercase">Used</span>
                        </div>
                    </div>
                    <p className="text-xs text-[#8b8b96] mt-2">Budget Utilization</p>
                </div>

                {/* Budget Stats */}
                <div className="col-span-2 grid grid-cols-2 gap-4">
                    <div className="card">
                        <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Total Budget</p>
                        <p className="text-3xl font-bold text-white">${total.toLocaleString()}</p>
                    </div>
                    <div className="card">
                        <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Spent</p>
                        <p className="text-3xl font-bold text-[#4c6ef5]">${spent.toLocaleString()}</p>
                    </div>
                    <div className="card">
                        <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Remaining</p>
                        <p className="text-3xl font-bold text-[#40c057]">${remaining.toLocaleString()}</p>
                    </div>
                    <div className="card">
                        <p className="text-xs text-[#8b8b96] uppercase tracking-wider mb-1">Approval Tiers</p>
                        <div className="space-y-1 mt-1">
                            <div className="flex items-center gap-2 text-xs">
                                <span className="badge badge-green text-[9px]">AUTO</span>
                                <span className="text-[#8b8b96]">≤ 30% remaining</span>
                            </div>
                            <div className="flex items-center gap-2 text-xs">
                                <span className="badge badge-blue text-[9px]">AI</span>
                                <span className="text-[#8b8b96]">≤ 70% remaining</span>
                            </div>
                            <div className="flex items-center gap-2 text-xs">
                                <span className="badge badge-red text-[9px]">ESCALATE</span>
                                <span className="text-[#8b8b96]">&gt; 70% remaining</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Transaction History */}
            <div className="card p-0 overflow-hidden">
                <div className="p-4 border-b border-[#2a2a35]">
                    <h3 className="text-sm font-semibold text-[#8b8b96] uppercase tracking-wider">
                        Transaction History
                    </h3>
                </div>
                {transactions.length === 0 ? (
                    <div className="p-8 text-center text-[#8b8b96]">No transactions yet.</div>
                ) : (
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Order</th>
                                <th>Amount</th>
                                <th>Status</th>
                                <th>Reason</th>
                                <th>Date</th>
                            </tr>
                        </thead>
                        <tbody>
                            {transactions.map((txn: any) => (
                                <tr key={txn.id}>
                                    <td className="font-mono text-[#8b8b96]">#{txn.id}</td>
                                    <td className="font-mono text-[#4c6ef5]">
                                        {txn.order_id ? `#${txn.order_id}` : '—'}
                                    </td>
                                    <td className="font-mono font-semibold text-white">
                                        ${parseFloat(txn.amount).toFixed(2)}
                                    </td>
                                    <td>
                                        <span className={`badge ${txn.approved ? 'badge-green' : 'badge-red'}`}>
                                            {txn.approved ? 'APPROVED' : 'REJECTED'}
                                        </span>
                                    </td>
                                    <td className="text-[#8b8b96] text-xs max-w-[200px] truncate">
                                        {txn.reason || '—'}
                                    </td>
                                    <td className="text-[#8b8b96] text-xs">
                                        {new Date(txn.created_at).toLocaleString()}
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
