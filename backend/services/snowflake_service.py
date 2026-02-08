"""
Synapse 2.0 Snowflake Cortex Service
Patient data retrieval and RAG queries using Snowflake Cortex AI functions

References:
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-llm-functions
"""

import asyncio
import logging
from typing import Optional
from datetime import datetime
import json
import re

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
    logger.warning("Snowflake connector not available.")



class SnowflakeService:
    """
    Snowflake Cortex integration for:
    - Patient history (structured SQL data)
    - Clinical guidelines RAG (Cortex EMBED_TEXT_768 + VECTOR_COSINE_SIMILARITY)
    - LLM inference (Cortex COMPLETE)
    - Session persistence
    """

    def __init__(self):
        self.settings = get_settings()
        self._connection = None

    async def connect(self) -> bool:
        """Establish connection to Snowflake (runs sync connect in a thread)"""
        if not SNOWFLAKE_AVAILABLE:
            logger.error("Snowflake connector not installed")
            return False

        if not self.settings.snowflake_account:
            logger.error("Snowflake not configured — set SNOWFLAKE_ACCOUNT in .env")
            return False

        try:
            self._connection = await asyncio.to_thread(
                snowflake.connector.connect,
                account=self.settings.snowflake_account,
                user=self.settings.snowflake_user,
                password=self.settings.snowflake_password,
                database=self.settings.snowflake_database,
                schema=self.settings.snowflake_schema,
                warehouse=self.settings.snowflake_warehouse,
            )
            logger.info("Connected to Snowflake successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Snowflake: {e}")
            return False

    async def disconnect(self) -> None:
        """Close Snowflake connection"""
        if self._connection:
            await asyncio.to_thread(self._connection.close)
            self._connection = None

    # ------------------------------------------------------------------
    # Internal helper: run sync Snowflake queries off the event loop
    # ------------------------------------------------------------------

    def _execute_query(self, sql: str, params: tuple = (), use_dict: bool = False):
        """Synchronous query execution (called via asyncio.to_thread)"""
        cursor = self._connection.cursor(DictCursor) if use_dict else self._connection.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()

    def _execute_single(self, sql: str, params: tuple = (), use_dict: bool = False):
        """Synchronous single-row fetch"""
        cursor = self._connection.cursor(DictCursor) if use_dict else self._connection.cursor()
        cursor.execute(sql, params)
        return cursor.fetchone()

    def _execute_write(self, sql: str, params: tuple = ()):
        """Synchronous write + commit"""
        cursor = self._connection.cursor()
        cursor.execute(sql, params)
        self._connection.commit()

    # ------------------------------------------------------------------
    # Patient data
    # ------------------------------------------------------------------

    async def list_patients(self) -> list[dict]:
        """Return all patients from Snowflake."""
        if not self._connection:
            logger.error("No Snowflake connection — cannot list patients")
            return []

        try:
            rows = await asyncio.to_thread(
                self._execute_query,
                "SELECT PATIENT_ID, NAME FROM PATIENT_DATA ORDER BY NAME",
                (),
                True,
            )
            return [{"id": row["PATIENT_ID"], "name": row["NAME"]} for row in rows]
        except Exception as e:
            logger.error(f"Error listing patients: {e}")
            return []

    async def get_patient_data(self, patient_id: str) -> Optional[PatientData]:
        """Retrieve patient data from Snowflake."""
        if not self._connection:
            logger.error(f"No Snowflake connection — cannot retrieve patient {patient_id}")
            return None

        try:
            # Query patient demographics
            patient_row = await asyncio.to_thread(
                self._execute_single,
                "SELECT * FROM PATIENT_DATA WHERE PATIENT_ID = %s",
                (patient_id,),
                True,
            )

            if not patient_row:
                logger.warning(f"Patient {patient_id} not found in Snowflake")
                return None

            # Query active medications
            med_rows = await asyncio.to_thread(
                self._execute_query,
                "SELECT * FROM PATIENT_MEDICATIONS WHERE PATIENT_ID = %s AND ACTIVE = TRUE",
                (patient_id,),
                True,
            )

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
            allergy_rows = await asyncio.to_thread(
                self._execute_query,
                "SELECT ALLERGEN FROM PATIENT_ALLERGIES WHERE PATIENT_ID = %s",
                (patient_id,),
                True,
            )
            allergies = [row["ALLERGEN"] for row in allergy_rows]

            # Parse comma-separated history fields
            raw_history = patient_row.get("MEDICAL_HISTORY") or ""
            raw_diagnoses = patient_row.get("RECENT_DIAGNOSES") or ""

            return PatientData(
                patient_id=patient_id,
                name=patient_row["NAME"],
                date_of_birth=patient_row["DATE_OF_BIRTH"],
                allergies=allergies,
                current_medications=medications,
                medical_history=[h.strip() for h in raw_history.split(",") if h.strip()],
                recent_diagnoses=[d.strip() for d in raw_diagnoses.split(",") if d.strip()],
            )

        except Exception as e:
            logger.error(f"Error retrieving patient data: {e}")
            return None

    async def get_patient_medications(self, patient_id: str) -> list[Medication]:
        """Get just the medications for a patient"""
        patient = await self.get_patient_data(patient_id)
        return patient.current_medications if patient else []

    # ------------------------------------------------------------------
    # Cortex COMPLETE — LLM inference
    # ------------------------------------------------------------------

    async def cortex_complete(
        self,
        prompt: str,
        model: str = "claude-3-5-sonnet",
    ) -> Optional[str]:
        """
        Use Snowflake Cortex COMPLETE for LLM inference.

        SQL: SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)
        """
        if not self._connection:
            logger.info("Cortex not available — no connection")
            return None

        try:
            row = await asyncio.to_thread(
                self._execute_single,
                "SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s) AS response",
                (model, prompt),
            )
            return row[0] if row else None

        except Exception as e:
            logger.error(f"Cortex COMPLETE error: {e}")
            return None

    # ------------------------------------------------------------------
    # Clinical guidelines RAG search
    # ------------------------------------------------------------------

    async def search_clinical_guidelines(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        """
        Semantic search over CLINICAL_GUIDELINES using Cortex embeddings.

        Embeds the query inline with EMBED_TEXT_768, then ranks guidelines by
        VECTOR_COSINE_SIMILARITY against pre-computed embeddings.
        """
        if not self._connection:
            logger.info(f"No Snowflake connection — returning empty guidelines for: {query}")
            return []

        try:
            rows = await asyncio.to_thread(
                self._execute_query,
                """
                SELECT
                    SOURCE,
                    TITLE,
                    CONTENT,
                    VECTOR_COSINE_SIMILARITY(
                        EMBEDDING,
                        SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', %s)
                    ) AS RELEVANCE_SCORE
                FROM CLINICAL_GUIDELINES
                WHERE EMBEDDING IS NOT NULL
                ORDER BY RELEVANCE_SCORE DESC
                LIMIT %s
                """,
                (query, limit),
                True,
            )

            return [
                {
                    "source": row["SOURCE"],
                    "title": row["TITLE"],
                    "content": row["CONTENT"],
                    "relevance_score": float(row["RELEVANCE_SCORE"]),
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Error searching guidelines: {e}")
            return []

    # ------------------------------------------------------------------
    # Medical entity extraction via Cortex COMPLETE
    # ------------------------------------------------------------------

    async def extract_medical_entities(self, text: str) -> dict:
        """
        Extract medications, conditions, and procedures from clinical text
        using Cortex COMPLETE.
        """
        prompt = f"""Extract medical entities from this clinical text.
Return ONLY valid JSON with keys: medications (list of objects with name and dosage), conditions (list of strings), procedures (list of strings).

Text: {text}"""

        result = await self.cortex_complete(prompt)
        if result:
            try:
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    return json.loads(json_match.group())
            except (json.JSONDecodeError, AttributeError):
                logger.error("Failed to parse entity extraction response")

        return {"medications": [], "conditions": [], "procedures": []}

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    async def save_session_record(self, session_data: dict) -> bool:
        """Save completed session to Snowflake CLINICAL_SESSIONS table"""
        if not self._connection:
            logger.info(f"No Snowflake connection — skipping save for session: {session_data.get('session_id')}")
            return True

        try:
            await asyncio.to_thread(
                self._execute_write,
                """
                INSERT INTO CLINICAL_SESSIONS
                (SESSION_ID, PATIENT_ID, PROVIDER_ID, START_TIME, END_TIME,
                 TRANSCRIPT, SOAP_NOTE, SAFETY_ALERTS, BILLING_INFO)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_data["session_id"],
                    session_data["patient_id"],
                    session_data["provider_id"],
                    session_data["start_time"],
                    session_data["end_time"],
                    session_data.get("transcript", ""),
                    session_data.get("soap_note", ""),
                    session_data.get("safety_alerts", ""),
                    session_data.get("billing_info", ""),
                ),
            )
            logger.info(f"Session {session_data['session_id']} saved to Snowflake")
            return True
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False
