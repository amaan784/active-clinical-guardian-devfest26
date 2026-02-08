"""
Synapse 2.0 Snowflake Cortex Service
Patient data retrieval and RAG queries using Snowflake Cortex AI functions

References:
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-rest-api
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql
"""

import logging
from typing import Optional
from datetime import datetime
import json
import httpx

from config import get_settings
from models.schemas import PatientData, Medication

logger = logging.getLogger(__name__)

# Conditional import for Snowflake
try:
    import snowflake.connector
    from snowflake.connector import DictCursor
    SNOWFLAKE_AVAILABLE = True
except ImportError:
    SNOWFLAKE_AVAILABLE = False
    logger.warning("Snowflake connector not available. Using mock data.")


class SnowflakeService:
    """
    Snowflake Cortex integration for:
    - Patient history (structured SQL data)
    - Clinical guidelines RAG (Cortex AI functions)
    - AI-powered text extraction and analysis

    Uses Snowflake Cortex AI SQL functions:
    - AI_COMPLETE: LLM text generation
    - AI_EMBED: Text embeddings for similarity search
    - AI_EXTRACT: Information extraction from documents
    """

    def __init__(self):
        self.settings = get_settings()
        self._connection = None
        self._rest_client: Optional[httpx.AsyncClient] = None

        # Demo patient data for hackathon
        self._demo_patients = {
            "P001": PatientData(
                patient_id="P001",
                name="Amaan Patel",
                date_of_birth=datetime(1985, 3, 15),
                allergies=["Penicillin", "Sulfa drugs"],
                current_medications=[
                    Medication(
                        name="Sertraline",
                        dosage="100mg",
                        frequency="Once daily",
                        drug_class="SSRI"
                    ),
                    Medication(
                        name="Lisinopril",
                        dosage="10mg",
                        frequency="Once daily",
                        drug_class="ACE Inhibitor"
                    ),
                ],
                medical_history=["Hypertension", "Generalized Anxiety Disorder"],
                recent_diagnoses=["Migraine without aura"]
            ),
            "P002": PatientData(
                patient_id="P002",
                name="Sarah Johnson",
                date_of_birth=datetime(1972, 8, 22),
                allergies=["Latex"],
                current_medications=[
                    Medication(
                        name="Warfarin",
                        dosage="5mg",
                        frequency="Once daily",
                        drug_class="Anticoagulant"
                    ),
                    Medication(
                        name="Metoprolol",
                        dosage="50mg",
                        frequency="Twice daily",
                        drug_class="Beta Blocker"
                    ),
                ],
                medical_history=["Atrial Fibrillation", "DVT History"],
                recent_diagnoses=["Chronic back pain"]
            ),
        }

    async def connect(self) -> bool:
        """Establish connection to Snowflake"""
        if not SNOWFLAKE_AVAILABLE:
            logger.info("Using demo mode - Snowflake not connected")
            return True

        if not self.settings.snowflake_account:
            logger.info("Snowflake not configured, using demo mode")
            return True

        try:
            self._connection = snowflake.connector.connect(
                account=self.settings.snowflake_account,
                user=self.settings.snowflake_user,
                password=self.settings.snowflake_password,
                database=self.settings.snowflake_database,
                schema=self.settings.snowflake_schema,
                warehouse=self.settings.snowflake_warehouse,
            )

            # Initialize REST client for Cortex API
            self._rest_client = httpx.AsyncClient(
                base_url=f"https://{self.settings.snowflake_account}.snowflakecomputing.com",
                timeout=60.0,
            )

            logger.info("Connected to Snowflake successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Snowflake: {e}")
            return False

    async def disconnect(self) -> None:
        """Close Snowflake connection"""
        if self._connection:
            self._connection.close()
            self._connection = None
        if self._rest_client:
            await self._rest_client.aclose()
            self._rest_client = None

    async def get_patient_data(self, patient_id: str) -> Optional[PatientData]:
        """Retrieve patient data from Snowflake"""
        # Demo mode - return from local cache
        if patient_id in self._demo_patients:
            logger.info(f"Retrieved demo patient data for {patient_id}")
            return self._demo_patients[patient_id]

        if not self._connection:
            logger.warning("No Snowflake connection, using demo data")
            return self._demo_patients.get("P001")

        try:
            cursor = self._connection.cursor(DictCursor)

            # Query patient demographics
            cursor.execute("""
                SELECT * FROM PATIENT_DATA WHERE PATIENT_ID = %s
            """, (patient_id,))
            patient_row = cursor.fetchone()

            if not patient_row:
                return None

            # Query medications
            cursor.execute("""
                SELECT * FROM PATIENT_MEDICATIONS WHERE PATIENT_ID = %s AND ACTIVE = TRUE
            """, (patient_id,))
            med_rows = cursor.fetchall()

            medications = [
                Medication(
                    name=row["MEDICATION_NAME"],
                    dosage=row["DOSAGE"],
                    frequency=row["FREQUENCY"],
                    drug_class=row.get("DRUG_CLASS"),
                )
                for row in med_rows
            ]

            # Query allergies
            cursor.execute("""
                SELECT ALLERGEN FROM PATIENT_ALLERGIES WHERE PATIENT_ID = %s
            """, (patient_id,))
            allergies = [row["ALLERGEN"] for row in cursor.fetchall()]

            return PatientData(
                patient_id=patient_id,
                name=patient_row["NAME"],
                date_of_birth=patient_row["DATE_OF_BIRTH"],
                allergies=allergies,
                current_medications=medications,
                medical_history=patient_row.get("MEDICAL_HISTORY", "").split(","),
                recent_diagnoses=patient_row.get("RECENT_DIAGNOSES", "").split(","),
            )

        except Exception as e:
            logger.error(f"Error retrieving patient data: {e}")
            return self._demo_patients.get("P001")

    async def get_patient_medications(self, patient_id: str) -> list[Medication]:
        """Get just the medications for a patient"""
        patient = await self.get_patient_data(patient_id)
        return patient.current_medications if patient else []

    async def cortex_complete(
        self,
        prompt: str,
        model: str = "claude-3-5-sonnet",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Optional[str]:
        """
        Use Snowflake Cortex AI_COMPLETE for LLM inference

        REST API: POST /api/v2/cortex/inference:complete
        SQL: SELECT AI_COMPLETE(model, prompt, options)
        """
        if not self._connection:
            logger.info("Cortex not available, returning None")
            return None

        try:
            cursor = self._connection.cursor()

            # Use AI_COMPLETE SQL function
            cursor.execute("""
                SELECT SNOWFLAKE.CORTEX.AI_COMPLETE(
                    %s,
                    %s,
                    {'max_tokens': %s, 'temperature': %s}
                ) AS response
            """, (model, prompt, max_tokens, temperature))

            result = cursor.fetchone()
            if result:
                return result[0]
            return None

        except Exception as e:
            logger.error(f"Cortex AI_COMPLETE error: {e}")
            return None

    async def cortex_embed(self, text: str, model: str = "e5-base-v2") -> Optional[list[float]]:
        """
        Create text embeddings using Snowflake Cortex AI_EMBED

        REST API: POST /api/v2/cortex/inference:embed
        SQL: SELECT AI_EMBED(model, text)
        """
        if not self._connection:
            return None

        try:
            cursor = self._connection.cursor()

            cursor.execute("""
                SELECT SNOWFLAKE.CORTEX.AI_EMBED(%s, %s) AS embedding
            """, (model, text))

            result = cursor.fetchone()
            if result:
                return result[0]
            return None

        except Exception as e:
            logger.error(f"Cortex AI_EMBED error: {e}")
            return None

    async def search_clinical_guidelines(
        self,
        query: str,
        limit: int = 5
    ) -> list[dict]:
        """
        Search clinical guidelines using Snowflake Cortex

        Uses AI_EMBED for semantic search over vectorized clinical PDFs
        """
        # Demo mode - return mock guideline data
        mock_guidelines = [
            {
                "source": "FDA Drug Safety Communication",
                "title": "Serotonin Syndrome Warning",
                "content": "Concurrent use of triptans (e.g., sumatriptan, rizatriptan) with SSRIs or SNRIs may result in serotonin syndrome. Symptoms include agitation, hallucinations, rapid heartbeat, fever, muscle stiffness, and loss of coordination. Healthcare providers should carefully weigh the potential risk of serotonin syndrome against the expected benefit of treatment.",
                "relevance_score": 0.95,
            },
            {
                "source": "Clinical Pharmacology Guidelines",
                "title": "SSRI Drug Interactions",
                "content": "Selective serotonin reuptake inhibitors (SSRIs) including sertraline, fluoxetine, and paroxetine can interact with numerous medications. Key interactions include: MAO inhibitors (contraindicated), triptans (serotonin syndrome risk), anticoagulants (increased bleeding risk), and NSAIDs (GI bleeding risk).",
                "relevance_score": 0.88,
            },
            {
                "source": "Migraine Treatment Protocol",
                "title": "Triptan Prescribing Guidelines",
                "content": "When prescribing triptans for migraine, verify patient is not taking serotonergic medications. Alternative treatments for patients on SSRIs include: gepants (ubrogepant, rimegepant), NSAIDs, or combination acetaminophen/caffeine. If triptan use is necessary, use lowest effective dose and monitor for serotonin syndrome symptoms.",
                "relevance_score": 0.82,
            },
        ]

        if not self._connection:
            logger.info(f"Returning mock guidelines for query: {query}")
            return mock_guidelines[:limit]

        try:
            cursor = self._connection.cursor(DictCursor)

            # Get query embedding
            query_embedding = await self.cortex_embed(query)
            if not query_embedding:
                return mock_guidelines[:limit]

            # Search using vector similarity
            # Assumes CLINICAL_GUIDELINES table has EMBEDDING column
            cursor.execute("""
                SELECT
                    SOURCE,
                    TITLE,
                    CONTENT,
                    VECTOR_COSINE_SIMILARITY(EMBEDDING, %s::VECTOR) as RELEVANCE_SCORE
                FROM CLINICAL_GUIDELINES
                ORDER BY RELEVANCE_SCORE DESC
                LIMIT %s
            """, (json.dumps(query_embedding), limit))

            results = cursor.fetchall()

            return [
                {
                    "source": row["SOURCE"],
                    "title": row["TITLE"],
                    "content": row["CONTENT"],
                    "relevance_score": float(row["RELEVANCE_SCORE"]),
                }
                for row in results
            ]

        except Exception as e:
            logger.error(f"Error searching guidelines: {e}")
            return mock_guidelines[:limit]

    async def extract_medical_entities(self, text: str) -> dict:
        """
        Extract medical entities from text using Cortex AI_EXTRACT

        Extracts medications, dosages, conditions, and procedures
        """
        if not self._connection:
            return {"medications": [], "conditions": [], "procedures": []}

        try:
            cursor = self._connection.cursor()

            prompt = f"""Extract medical entities from this clinical text.
Return JSON with: medications (name, dosage), conditions, procedures.

Text: {text}"""

            cursor.execute("""
                SELECT SNOWFLAKE.CORTEX.AI_EXTRACT(
                    'claude-3-5-sonnet',
                    %s,
                    {'output_format': 'json'}
                ) AS entities
            """, (prompt,))

            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return {"medications": [], "conditions": [], "procedures": []}

        except Exception as e:
            logger.error(f"Cortex AI_EXTRACT error: {e}")
            return {"medications": [], "conditions": [], "procedures": []}

    async def save_session_record(self, session_data: dict) -> bool:
        """Save completed session to Snowflake for permanent record"""
        if not self._connection:
            logger.info(f"Would save session: {session_data.get('session_id')}")
            return True

        try:
            cursor = self._connection.cursor()
            cursor.execute("""
                INSERT INTO CLINICAL_SESSIONS
                (SESSION_ID, PATIENT_ID, PROVIDER_ID, START_TIME, END_TIME,
                 TRANSCRIPT, SOAP_NOTE, SAFETY_ALERTS, BILLING_INFO)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                session_data["session_id"],
                session_data["patient_id"],
                session_data["provider_id"],
                session_data["start_time"],
                session_data["end_time"],
                session_data.get("transcript", ""),
                session_data.get("soap_note", ""),
                session_data.get("safety_alerts", ""),
                session_data.get("billing_info", ""),
            ))
            self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False


# SQL setup script for Snowflake tables
SNOWFLAKE_SETUP_SQL = """
-- Create database and schema
CREATE DATABASE IF NOT EXISTS SYNAPSE_DB;
USE DATABASE SYNAPSE_DB;
CREATE SCHEMA IF NOT EXISTS PUBLIC;

-- Patient data table
CREATE TABLE IF NOT EXISTS PATIENT_DATA (
    PATIENT_ID VARCHAR PRIMARY KEY,
    NAME VARCHAR,
    DATE_OF_BIRTH DATE,
    MEDICAL_HISTORY VARCHAR,
    RECENT_DIAGNOSES VARCHAR,
    CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

-- Patient medications
CREATE TABLE IF NOT EXISTS PATIENT_MEDICATIONS (
    ID INTEGER AUTOINCREMENT PRIMARY KEY,
    PATIENT_ID VARCHAR REFERENCES PATIENT_DATA(PATIENT_ID),
    MEDICATION_NAME VARCHAR,
    DOSAGE VARCHAR,
    FREQUENCY VARCHAR,
    DRUG_CLASS VARCHAR,
    ACTIVE BOOLEAN DEFAULT TRUE,
    START_DATE DATE,
    PRESCRIBER VARCHAR
);

-- Patient allergies
CREATE TABLE IF NOT EXISTS PATIENT_ALLERGIES (
    ID INTEGER AUTOINCREMENT PRIMARY KEY,
    PATIENT_ID VARCHAR REFERENCES PATIENT_DATA(PATIENT_ID),
    ALLERGEN VARCHAR,
    SEVERITY VARCHAR,
    REACTION VARCHAR
);

-- Clinical guidelines with embeddings for RAG
CREATE TABLE IF NOT EXISTS CLINICAL_GUIDELINES (
    ID INTEGER AUTOINCREMENT PRIMARY KEY,
    SOURCE VARCHAR,
    TITLE VARCHAR,
    CONTENT TEXT,
    EMBEDDING VECTOR(FLOAT, 768),  -- e5-base-v2 embedding dimension
    CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

-- Clinical sessions
CREATE TABLE IF NOT EXISTS CLINICAL_SESSIONS (
    SESSION_ID VARCHAR PRIMARY KEY,
    PATIENT_ID VARCHAR,
    PROVIDER_ID VARCHAR,
    START_TIME TIMESTAMP,
    END_TIME TIMESTAMP,
    TRANSCRIPT TEXT,
    SOAP_NOTE TEXT,
    SAFETY_ALERTS TEXT,
    BILLING_INFO TEXT,
    CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

-- Grant Cortex access
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE PUBLIC;

-- Insert demo patient
INSERT INTO PATIENT_DATA (PATIENT_ID, NAME, DATE_OF_BIRTH, MEDICAL_HISTORY, RECENT_DIAGNOSES)
VALUES ('P001', 'Amaan Patel', '1985-03-15', 'Hypertension,Generalized Anxiety Disorder', 'Migraine without aura');

INSERT INTO PATIENT_MEDICATIONS (PATIENT_ID, MEDICATION_NAME, DOSAGE, FREQUENCY, DRUG_CLASS)
VALUES
    ('P001', 'Sertraline', '100mg', 'Once daily', 'SSRI'),
    ('P001', 'Lisinopril', '10mg', 'Once daily', 'ACE Inhibitor');

INSERT INTO PATIENT_ALLERGIES (PATIENT_ID, ALLERGEN, SEVERITY)
VALUES
    ('P001', 'Penicillin', 'Severe'),
    ('P001', 'Sulfa drugs', 'Moderate');
"""
