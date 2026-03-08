import { API_URL, WS_URL } from './api';

const MOCK_DATA = {
    '/health': {
        status: 'healthy',
        components: {
            'market-api': 'ok',
            'pricing-agent': 'ok',
            'inventory-agent': 'ok',
            'supplier-a': 'ok',
            'supplier-b': 'ok',
            'supplier-c': 'ok',
            'order-agent': 'ok',
            'finance-agent': 'ok',
            'notification-agent': 'ok'
        }
    },
    '/inventory': {
        products: [
            { name: 'Laptop', stock: 12, price: 999.00, value: 11988.00 },
            { name: 'Monitor', stock: 45, price: 300.00, value: 13500.00 },
            { name: 'Keyboard', stock: 110, price: 50.00, value: 5500.00 },
            { name: 'Mouse', stock: 95, price: 25.00, value: 2375.00 },
            { name: 'Webcam', stock: 18, price: 80.00, value: 1440.00 }
        ],
        total_value: 34803.00,
        low_stock_alerts: ['Laptop', 'Webcam']
    },
    '/finance/budget': {
        monthly_budget: 50000.0,
        spent: 12500.0,
        remaining: 37500.0,
        utilization_pct: 25.0,
        recent_transactions: [
            {
                id: 1,
                product: 'Laptop',
                supplier: 'SupplierB',
                quantity: 20,
                unit_price: 948.63,
                total_price: 18972.6,
                timestamp: new Date().toISOString(),
                status: 'approved',
                llm_reasoning: 'Within auto-approval budget parameters.'
            }
        ]
    },
    '/orders': {
        orders: [
            {
                id: 1,
                product: 'Laptop',
                supplier: 'SupplierB',
                quantity: 20,
                status: 'confirmed',
                timestamp: new Date().toISOString(),
                llm_score: 0.69,
                llm_reasoning: 'Choosing Supplier B because although they are $2 more, their 100% reliability is critical for our low inventory of Laptops.'
            },
            {
                id: 2,
                product: 'Monitor',
                supplier: 'SupplierA',
                quantity: 20,
                status: 'confirmed',
                timestamp: new Date(Date.now() - 3600000).toISOString(),
                llm_score: 0.81,
                llm_reasoning: 'Supplier A provides the best overall score for Monitors based on historical delivery reliability and price.'
            }
        ]
    },
    '/prices': {
        current_prices: {
            'Laptop': 999.00,
            'Monitor': 300.00,
            'Keyboard': 50.00,
            'Mouse': 25.00,
            'Webcam': 80.00
        },
        market_trend: 'stable'
    }
};

class MockWebSocket {
    onmessage: ((ev: any) => void) | null = null;
    onopen: ((ev: any) => void) | null = null;
    onclose: ((ev: any) => void) | null = null;

    constructor() {
        setTimeout(() => {
            if (this.onopen) this.onopen({ type: 'open' });
        }, 100);
    }

    send(data: string) {
        // Simulate pipeline run
        const events = [
            { step: 'start', message: 'Pipeline triggered via Next.js mock UI', status: 'started' },
            { step: 'price_sync', message: 'Synced latest market prices', status: 'completed' },
            { step: 'inventory_check', message: 'Detected low stock: Laptop (qty=12)', status: 'info' },
            { step: 'bidding', message: 'Supplier A bid: $990 (4d), Supplier B bid: $1050 (2d)', status: 'completed' },
            { step: 'finance_approval', message: 'Budget approved by Finance Agent', status: 'completed' },
            { step: 'order_confirmed', message: '20 x Laptop ordered from Supplier B', status: 'completed' },
            { step: 'notification', message: 'Restock alert email sent', status: 'completed' }
        ];

        let delay = 500;
        for (const event of events) {
            setTimeout(() => {
                if (this.onmessage) {
                    this.onmessage({ data: JSON.stringify(event) });
                }
            }, delay);
            delay += 1000;
        }
    }

    close() {
        if (this.onclose) this.onclose({ type: 'close' });
    }
}

export function handleMockRequest(path: string) {
    return new Promise((resolve) => {
        setTimeout(() => {
            const data = (MOCK_DATA as any)[path] || {};
            resolve(data);
        }, 300);
    });
}

export function createMockWebSocket() {
    return new MockWebSocket() as any as WebSocket;
}
