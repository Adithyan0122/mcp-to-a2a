# AI Supply Chain System v1.0

This repository contains a multi-agent supply chain system orchestrating 9 independent Python FastAPIs, powered by Google Gemini AI, PostgreSQL, Redis, and Celery, alongside a Next.js frontend dashboard.

## 🚀 Live Demo (Mock Version)
You can deploy the Next.js frontend to [Vercel](https://vercel.com/) by pointing it to the `v1.0/frontend` directory and adding the environment variable `NEXT_PUBLIC_MOCK_MODE=true`. This will run a simulated version of the dashboard without needing to deploy the 9 backend microservices.

## 💻 Local Setup (Full AI Engine)

To run the full multi-agent system, ensure you have Docker and Docker Compose installed.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Adithyan0122/mcp-to-a2a.git
   cd mcp-to-a2a/v1.0
   ```

2. **Configure Environment:**
   Copy the example environment file and add your Google Gemini API key.
   ```bash
   cp .env.example .env
   ```
   Open `.env` and configure `GEMINI_API_KEY=your_key_here`.

3. **Start the System:**
   ```bash
   docker compose up --build
   ```

4. **Access the Dashboard:**
   Open `http://localhost:3000` in your browser to view the AI agents making real-time pricing and inventory decisions.

## Architecture
- **Agents:** Pricing, Inventory, Order, Finance, Notification, 3x Suppliers, Market API
- **AI Core:** Google Gemini 2.5 Flash for agent reasoning
- **Frontend:** Next.js 14, TailwindCSS, Recharts
- **Infrastructure:** Docker Compose, PostgreSQL processing layer, Redis & Celery messaging
