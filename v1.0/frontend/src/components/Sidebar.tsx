'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV_ITEMS = [
    { href: '/', label: 'Inventory', icon: '📦' },
    { href: '/pipeline', label: 'Pipeline', icon: '⚡' },
    { href: '/orders', label: 'Orders', icon: '📋' },
    { href: '/agents', label: 'Agents', icon: '🤖' },
    { href: '/market', label: 'Market', icon: '📈' },
    { href: '/budget', label: 'Budget', icon: '💰' },
];

export default function Sidebar() {
    const pathname = usePathname();

    return (
        <aside className="fixed left-0 top-0 h-screen w-64 bg-[#111118] border-r border-[#2a2a35] flex flex-col z-50">
            {/* Logo */}
            <div className="p-6 border-b border-[#2a2a35]">
                <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg flex items-center justify-center text-lg"
                        style={{ background: 'linear-gradient(135deg, #4c6ef5, #7950f2)' }}>
                        ⛓
                    </div>
                    <div>
                        <h1 className="text-sm font-bold text-white tracking-tight">Supply Chain</h1>
                        <span className="text-[10px] font-mono text-[#8b8b96]">v1.0 AI-POWERED</span>
                    </div>
                </div>
            </div>

            {/* Navigation */}
            <nav className="flex-1 p-4 space-y-1">
                {NAV_ITEMS.map(item => {
                    const isActive = pathname === item.href;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200
                ${isActive
                                    ? 'bg-[#4c6ef5]/10 text-[#4c6ef5] border border-[#4c6ef5]/20'
                                    : 'text-[#8b8b96] hover:text-white hover:bg-[#1c1c25]'
                                }`}
                        >
                            <span className="text-base">{item.icon}</span>
                            {item.label}
                        </Link>
                    );
                })}
            </nav>

            {/* Status Footer */}
            <div className="p-4 border-t border-[#2a2a35]">
                <div className="flex items-center gap-2 text-xs text-[#8b8b96]">
                    <div className="pulse-dot bg-[#40c057]" />
                    <span>System Online</span>
                </div>
            </div>
        </aside>
    );
}
