"""
Synapse 2.0 Snowflake Cortex Service
Handles patient data retrieval and RAG queries for clinical guidelines
"""

import logging
from typing import Optional
from datetime import datetime

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
    - Clinical guidelines (vectorized PDFs via Cortex Search)
    """

    def __init__(self):
        self.settings = get_settings()
        self._connection = None

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

        try:
            self._connection = snowflake.connector.connect(
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
            self._connection.close()
            self._connection = None

    async def get_patient_data(self, patient_id: str) -> Optional[PatientData]:
        """
        Retrieve patient data from Snowflake

        Args:
            patient_id: The patient identifier

        Returns:
            PatientData object or None if not found
        """
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

    async def search_clinical_guidelines(
        self,
        query: str,
        limit: int = 5
    ) -> list[dict]:
        """
        Search clinical guidelines using Snowflake Cortex RAG

        Uses Cortex Search to find relevant guidelines from vectorized PDFs

        Args:
            query: Natural language search query
            limit: Maximum number of results

        Returns:
            List of relevant guideline excerpts
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

            # Use Cortex Search for semantic search
            cursor.execute("""
                SELECT
                    source,
                    title,
                    content,
                    CORTEX_SEARCH_SCORE() as relevance_score
                FROM CLINICAL_GUIDELINES
                WHERE CORTEX_SEARCH(content, %s)
                ORDER BY relevance_score DESC
                LIMIT %s
            """, (query, limit))

            results = cursor.fetchall()

            return [
                {
                    "source": row["SOURCE"],
                    "title": row["TITLE"],
                    "content": row["CONTENT"],
                    "relevance_score": row["RELEVANCE_SCORE"],
                }
                for row in results
            ]

        except Exception as e:
            logger.error(f"Error searching guidelines: {e}")
            return mock_guidelines[:limit]

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
