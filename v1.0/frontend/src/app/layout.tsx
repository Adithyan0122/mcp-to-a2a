import type { Metadata } from 'next';
import './globals.css';
import Sidebar from '@/components/Sidebar';

export const metadata: Metadata = {
    title: 'Supply Chain Dashboard v1.0',
    description: 'Production-grade AI-powered supply chain monitoring and control',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
    return (
        <html lang="en">
            <body className="flex flex-col min-h-screen">
                {process.env.NEXT_PUBLIC_MOCK_MODE === 'true' && (
                    <div className="bg-yellow-600/20 border-b border-yellow-500 text-yellow-100 p-2 text-center text-sm font-medium z-50">
                        This is a live mock demo to show the UI. To run the full AI-powered multi-agent backend, visit <a href="https://github.com/Adithyan0122/mcp-to-a2a" target="_blank" rel="noreferrer" className="underline font-bold hover:text-white">the GitHub Repository</a>.
                    </div>
                )}
                <div className="flex flex-1">
                    <Sidebar />
                    <main className="flex-1 ml-64 p-8 w-full">
                        {children}
                    </main>
                </div>
            </body>
        </html>
    );
}
