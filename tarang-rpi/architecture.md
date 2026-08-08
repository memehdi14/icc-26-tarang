# Tarang RPi Architecture

If by **strongest** you mean **best architecture for a professional, scalable biomedical IoT product that still runs well on a Raspberry Pi 4**, then this is the architecture recommended.

```text
                    Internet / LAN
                           │
                     HTTPS / HTTP
                           │
                    ┌──────────────┐
                    │    Nginx     │
                    │ Reverse Proxy│
                    └──────┬───────┘
                           │
            ┌──────────────┴──────────────┐
            │                             │
     Next.js Dashboard             FastAPI REST API
     (React + TypeScript)          + WebSocket Server
            │                             │
            └──────────────┬──────────────┘
                           │
                  Internal Event Bus
                           │
      ┌──────────────┬───────────────┬──────────────┐
      │              │               │              │
 BLE Gateway     AI Service      Data Service   Alert Engine
 (Bleak)         (Inference)     (DB Layer)     (Rules)
      │              │               │              │
      └──────────────┴───────────────┴──────────────┘
                           │
                    PostgreSQL Database
                           │
             ECG / PPG / Logs / CSV Metadata
                           │
                  SSD File Storage
                           │
────────────────────────────────────────────────────────

                 Raspberry Pi 4

────────────────────────────────────────────────────────
                           ▲
                           │
                 BLE 5.3 Notifications
                           │
                    EFR32MG26 Wearable
                           │
        ECG • PPG • IMU • Edge AI • DSP
```

## Technology Stack

| Layer           | Recommended                                                     |
| --------------- | --------------------------------------------------------------- |
| Frontend        | **Next.js + React + TypeScript**                                |
| Charts          | **Apache ECharts**                                              |
| Backend         | **FastAPI**                                                     |
| Real-time       | **WebSockets**                                                  |
| BLE             | **Bleak (Python)**                                              |
| Database        | **PostgreSQL**                                                  |
| ORM             | **SQLAlchemy**                                                  |
| Background Jobs | **Celery** (or FastAPI BackgroundTasks for smaller deployments) |
| Reverse Proxy   | **Nginx**                                                       |
| Authentication  | **JWT**                                                         |
| File Storage    | **SSD**                                                         |
| Deployment      | **Docker Compose**                                              |
| Startup         | **systemd** (or Docker restart policies)                        |

## Why this is the strongest

* Modern, industry-standard architecture.
* Clear separation between BLE communication, business logic, AI inference, and UI.
* Handles multiple dashboard users efficiently.
* Easy to add cloud synchronization later.
* Scales well if you later move from Raspberry Pi to a server or Kubernetes.
* Next.js provides an excellent user experience.
* FastAPI is one of the highest-performance Python web frameworks.
* PostgreSQL is reliable for long-term medical telemetry storage.
* Nginx manages HTTPS, compression, and reverse proxying.
* Docker Compose simplifies deployment and updates.

## Architecture Improvement: Independent BLE Gateway

**Keep the BLE gateway as its own service instead of embedding it inside FastAPI**.

```text
EFR32MG26
      │
 BLE Notifications
      │
      ▼
 BLE Gateway (Bleak)
      │
 Event Queue
      │
 FastAPI
      │
 PostgreSQL
      │
 Next.js
```

This ensures that Bluetooth communication continues uninterrupted even if the web server is busy or restarted.

For a project like Tarang, this architecture is close to what you would see in a commercial IoT healthcare product while remaining practical to run on a Raspberry Pi 4.
