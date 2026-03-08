import { handleMockRequest, createMockWebSocket } from './mock';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080';
const IS_MOCK = process.env.NEXT_PUBLIC_MOCK_MODE === 'true';

export async function fetchApi(path: string) {
    if (IS_MOCK) return handleMockRequest(path);
    const res = await fetch(`${API_URL}${path}`);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
}

export function fetcher(path: string) {
    return fetchApi(path);
}

export async function postApi(path: string, body?: any) {
    if (IS_MOCK) return handleMockRequest(path); // mock same data for POST
    const res = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
    });
    return res.json();
}

export function createWebSocket(path: string): WebSocket {
    if (IS_MOCK) return createMockWebSocket();
    return new WebSocket(`${WS_URL}${path}`);
}

export { API_URL, WS_URL };
