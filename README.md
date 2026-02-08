# Synapse 2.0 - The Active Clinical Guardian

Real-time clinical safety monitoring system that listens to doctor-patient encounters, validates drug safety using AI reasoning, and interrupts via voice when dangerous conditions are detected.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ Patient Card│  │ Transcript  │  │ Safety Panel│              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│                         │                                        │
│              WebSocket (Audio + JSON)                            │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                    Backend (FastAPI)                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │         Clinical Agent (Dedalus SDK Orchestration)       │    │
│  │   States: IDLE → LISTENING → PROCESSING → INTERRUPTING  │    │
│  └─────────────────────────────────────────────────────────┘    │
│         │              │              │              │           │
│    ┌────▼────┐   ┌────▼────┐   ┌────▼────┐   ┌────▼────┐       │
│    │Snowflake│   │K2 Think │   │ElevenLabs│  │Flowglad │       │
│    │ Cortex  │   │ (vLLM)  │   │  Voice   │  │ Billing │       │
│    └─────────┘   └─────────┘   └─────────┘   └─────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

## Features

- **Real-time Transcription**: Live doctor-patient conversation transcription
- **Safety Monitoring**: Continuous drug interaction checking against patient history
- **Voice Interruption**: Immediate audio alerts for dangerous prescriptions
- **Auto-Documentation**: SOAP note generation from encounter transcript
- **Automated Billing**: CPT/ICD-10 code generation and invoice creation

## Integrations & Documentation

| Service | Purpose | Documentation |
|---------|---------|---------------|
| **Dedalus Labs** | Agent orchestration, MCP tools | [docs.dedaluslabs.ai](https://docs.dedaluslabs.ai) / [GitHub SDK](https://github.com/dedalus-labs/dedalus-sdk-python) |
| **K2 Think V2** | Drug safety reasoning (70B model) | [HuggingFace](https://huggingface.co/LLM360/K2-Think-V2) / [IFM.ai](https://ifm.ai/) |
| **Snowflake Cortex** | Patient data RAG | [Snowflake Docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex) |
| **ElevenLabs** | Voice synthesis | [ElevenLabs Docs](https://elevenlabs.io/docs) |
| **Flowglad** | Billing automation | [Flowglad API](https://flowglad.com) |

## Tech Stack

### Backend
- Python 3.11 + FastAPI + WebSocket
- **dedalus_labs** SDK for agent orchestration
- **openai** SDK for K2 Think (OpenAI-compatible API via vLLM)
- Snowflake Cortex for patient data and clinical guidelines RAG
- ElevenLabs for voice synthesis

### Frontend
- Next.js 14 (App Router)
- Tailwind CSS + Shadcn/UI components
- WebSocket for real-time updates
- Web Audio API for recording/playback

## Quick Start

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file and configure
cp .env.example .env
# Edit .env with your API keys

# Run the server
python main.py
# Or: uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Copy environment file
cp .env.example .env.local

# Run development server
npm run dev
```

Open http://localhost:3000 in your browser.

### K2 Think Setup (Optional)

To use K2 Think for advanced reasoning, deploy via vLLM:

```bash
# Install vLLM
pip install vllm

# Serve K2 Think V2 model
vllm serve LLM360/K2-Think-V2 \
  --tensor_parallel_size 8 \
  --port 8080

# Update .env
K2_BASE_URL=http://localhost:8080/v1
K2_MODEL=LLM360/K2-Think-V2
```

Without K2 Think, the system falls back to rule-based drug interaction checking.

## Demo Flow

1. **Select Patient**: Choose a demo patient (e.g., "Amaan Patel" with SSRI history)
2. **Start Consultation**: Begin the clinical encounter
3. **Speak/Type**: Use microphone or type transcript manually
4. **Trigger Alert**: Click "Demo: Trigger Alert" or mention "sumatriptan"
5. **See Interruption**: Watch the system detect the SSRI-Triptan interaction
6. **End Consultation**: Generate SOAP note and billing

## API Endpoints

### REST

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/consult/start` | POST | Start a new consultation |
| `/api/consult/{id}/end` | POST | End consultation and generate billing |
| `/api/consult/{id}/status` | GET | Get session status |
| `/api/patients/{id}` | GET | Get patient data |
| `/api/demo/simulate-danger` | POST | Trigger a safety alert (demo) |

### WebSocket

Connect to `/ws/consult/{session_id}` for real-time:
- Audio streaming (binary)
- Transcript updates (JSON)
- Safety alerts (JSON)
- Voice interruptions (binary audio)

## Safety Logic

The system detects dangerous drug combinations:

| Drug Class 1 | Drug Class 2 | Risk |
|--------------|--------------|------|
| SSRI | Triptan | Serotonin Syndrome |
| SSRI | MAOI | Critical - Contraindicated |
| Anticoagulant | NSAID | Bleeding Risk |
| ACE Inhibitor | Potassium | Hyperkalemia |

With K2 Think enabled, the system uses advanced reasoning for more nuanced safety analysis beyond the rule-based fallback.

## Configuration

### Environment Variables

```bash
# Dedalus Labs (Agent Orchestration)
DEDALUS_API_KEY=your_dedalus_key

# K2 Think (OpenAI-compatible API)
K2_BASE_URL=http://localhost:8080/v1
K2_MODEL=LLM360/K2-Think-V2

# Snowflake
SNOWFLAKE_ACCOUNT=your_account
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password

# ElevenLabs
ELEVENLABS_API_KEY=your_key

# Flowglad
FLOWGLAD_API_KEY=your_key
```

## Deployment

### Backend (Vultr/Any VPS)
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Frontend (Vercel)
```bash
vercel deploy
```

## Prize Targeting

| Sponsor | Integration | Feature |
|---------|-------------|---------|
| Dedalus | `dedalus_labs` SDK | Agent orchestration with DedalusRunner |
| Snowflake | Cortex Search | Patient data + Clinical guidelines RAG |
| K2 Think (IFM) | OpenAI-compatible API | Drug interaction reasoning (70B model) |
| ElevenLabs | Turbo v2.5 WebSocket | Real-time TTS interruption |
| Flowglad | REST API | Automated CPT coding and invoicing |

## References

- [Dedalus Labs Documentation](https://docs.dedaluslabs.ai)
- [Dedalus Python SDK](https://github.com/dedalus-labs/dedalus-sdk-python)
- [K2 Think V2 on HuggingFace](https://huggingface.co/LLM360/K2-Think-V2)
- [IFM.ai - Institute of Foundation Models](https://ifm.ai/)
- [MBZUAI K2 Think Announcement](https://mbzuai.ac.ae/news/k2-think-v2-a-fully-sovereign-reasoning-model/)

## License

MIT
