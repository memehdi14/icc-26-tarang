# Agent Rules and Tasks: Tarang RPi Project

This document contains the base rules and detailed tasks for AI agents working on the `tarang-rpi` project.

## Base Rules for Agents

1. **Technology Stack Adherence**:
   - **Frontend**: Use **Next.js**, **React**, and **TypeScript**. Use **Apache ECharts** for all charting requirements.
   - **Backend** (Future): FastAPI with WebSockets.
   - **Styling**: Prioritize modern, premium, and dynamic UI design. Avoid generic colors. Use curated color palettes (e.g., sleek dark modes, vibrant accents). Use modern typography. Add smooth micro-animations. Ensure responsive layouts.
   - **Code Quality**: Write modular, reusable components. Document complex logic with comments. Adhere to strict TypeScript typing.
   
2. **Architecture Focus**:
   - The frontend is part of a larger, distributed system running on a Raspberry Pi 4.
   - Design frontend state and data-fetching mechanisms to seamlessly integrate with a future **FastAPI REST API** and **WebSocket Server** (for real-time ECG/PPG telemetry).
   - Assume API endpoints and WebSocket URLs will be configurable via environment variables (`.env`).
   
3. **Workflow**:
   - Always run Next.js development server using `npm run dev` to test changes locally.
   - Keep components focused. Do not mix business logic with UI rendering unnecessarily.
   - Ensure the UI remains highly performant, especially when rendering real-time high-frequency telemetry data (e.g., ECG waveforms) via ECharts.

## Detailed Tasks and Changes

### Phase 1: Initial Frontend Setup (Current Phase)

- [ ] **Initialize Next.js Project**:
  - Run `npx create-next-app@latest .` inside the `tarang-rpi/frontend` directory (using TypeScript, Tailwind CSS (if permitted by user/project styling config), and App Router).
- [ ] **Define Global Styles and Theme**:
  - Setup a premium dark-mode theme suitable for a medical dashboard.
  - Define core CSS variables (colors, typography, spacing).
- [ ] **Create Base Layout Structure**:
  - Implement a sidebar navigation for switching between different views (e.g., Dashboard, Patient Info, Historical Data, Settings).
  - Create a responsive top header.
- [ ] **Develop Dashboard View**:
  - **Telemetry Grid**: Create placeholders for real-time ECharts components (ECG, PPG, IMU data).
  - **Metrics Cards**: Display key vital signs (Heart Rate, SpO2) in clean, prominent cards.
  - **Status Indicators**: Show BLE connection status and backend sync status.
- [ ] **Implement ECharts Integration**:
  - Create a generic, reusable React wrapper for Apache ECharts.
  - Set up mock data streams to simulate high-frequency real-time updates (until the WebSocket backend is ready).

### Phase 2: Backend Integration (Future Phase)

- [ ] Connect ECharts to a live WebSocket feed for ECG/PPG data.
- [ ] Integrate REST API calls for historical data retrieval from PostgreSQL.
- [ ] Implement user authentication (JWT) flow if required for the dashboard.
- [ ] Handle BLE gateway connection status and alert notifications from the Alert Engine.
