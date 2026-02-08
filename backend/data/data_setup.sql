-- ============================================================
-- Synapse 2.0 - Snowflake Setup Script
-- Run this entire script in a Snowflake SQL Worksheet
-- ============================================================

-- STEP 1: Create database, schema, and warehouse
CREATE DATABASE IF NOT EXISTS SYNAPSE_DB;
USE DATABASE SYNAPSE_DB;
CREATE SCHEMA IF NOT EXISTS PUBLIC;
USE SCHEMA PUBLIC;
CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH
    WITH WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE;
USE WAREHOUSE COMPUTE_WH;

-- ============================================================
-- STEP 2: Create tables
-- ============================================================

CREATE TABLE IF NOT EXISTS PATIENT_DATA (
    PATIENT_ID VARCHAR PRIMARY KEY,
    NAME VARCHAR,
    DATE_OF_BIRTH DATE,
    MEDICAL_HISTORY VARCHAR,
    RECENT_DIAGNOSES VARCHAR,
    CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

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

CREATE TABLE IF NOT EXISTS PATIENT_ALLERGIES (
    ID INTEGER AUTOINCREMENT PRIMARY KEY,
    PATIENT_ID VARCHAR REFERENCES PATIENT_DATA(PATIENT_ID),
    ALLERGEN VARCHAR,
    SEVERITY VARCHAR,
    REACTION VARCHAR
);

CREATE TABLE IF NOT EXISTS CLINICAL_GUIDELINES (
    ID INTEGER AUTOINCREMENT PRIMARY KEY,
    SOURCE VARCHAR,
    TITLE VARCHAR,
    CONTENT TEXT,
    EMBEDDING VECTOR(FLOAT, 768),
    CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

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

-- ============================================================
-- STEP 3: Grant Cortex AI access
-- ============================================================
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE PUBLIC;

-- ============================================================
-- STEP 4: Insert demo patient P001 - Kevin Patel
-- Triggers: SSRI + Triptan = Serotonin Syndrome
-- ============================================================
INSERT INTO PATIENT_DATA (PATIENT_ID, NAME, DATE_OF_BIRTH, MEDICAL_HISTORY, RECENT_DIAGNOSES)
VALUES ('P001', 'Kevin Patel', '1985-03-15', 'Hypertension,Generalized Anxiety Disorder', 'Migraine without aura');

INSERT INTO PATIENT_MEDICATIONS (PATIENT_ID, MEDICATION_NAME, DOSAGE, FREQUENCY, DRUG_CLASS, ACTIVE)
VALUES
    ('P001', 'Sertraline', '100mg', 'Once daily', 'SSRI', TRUE),
    ('P001', 'Lisinopril', '10mg', 'Once daily', 'ACE Inhibitor', TRUE);

INSERT INTO PATIENT_ALLERGIES (PATIENT_ID, ALLERGEN, SEVERITY)
VALUES
    ('P001', 'Penicillin', 'Severe'),
    ('P001', 'Sulfa drugs', 'Moderate');

-- ============================================================
-- STEP 5: Insert demo patient P002 - Sarah Johnson
-- Triggers: Anticoagulant + NSAID = Bleeding Risk
-- ============================================================
INSERT INTO PATIENT_DATA (PATIENT_ID, NAME, DATE_OF_BIRTH, MEDICAL_HISTORY, RECENT_DIAGNOSES)
VALUES ('P002', 'Sarah Johnson', '1972-08-22', 'Atrial Fibrillation,DVT History', 'Chronic back pain');

INSERT INTO PATIENT_MEDICATIONS (PATIENT_ID, MEDICATION_NAME, DOSAGE, FREQUENCY, DRUG_CLASS, ACTIVE)
VALUES
    ('P002', 'Warfarin', '5mg', 'Once daily', 'Anticoagulant', TRUE),
    ('P002', 'Metoprolol', '50mg', 'Twice daily', 'Beta Blocker', TRUE);

INSERT INTO PATIENT_ALLERGIES (PATIENT_ID, ALLERGEN, SEVERITY)
VALUES
    ('P002', 'Latex', 'Moderate');

-- ============================================================
-- STEP 6: Insert clinical guidelines for RAG search
-- ============================================================
INSERT INTO CLINICAL_GUIDELINES (SOURCE, TITLE, CONTENT)
VALUES
    ('FDA Drug Safety Communication',
     'Serotonin Syndrome Warning - Triptans with SSRIs/SNRIs',
     'Concurrent use of triptans (e.g., sumatriptan, rizatriptan) with SSRIs or SNRIs may result in serotonin syndrome. Symptoms include agitation, hallucinations, rapid heartbeat, fever, muscle stiffness, and loss of coordination. Healthcare providers should carefully weigh the potential risk of serotonin syndrome against the expected benefit of treatment. If treatment is warranted, patients should be observed for serotonin syndrome symptoms, particularly during treatment initiation and dose increases.');

INSERT INTO CLINICAL_GUIDELINES (SOURCE, TITLE, CONTENT)
VALUES
    ('Clinical Pharmacology Guidelines',
     'SSRI Drug Interaction Profile',
     'Selective serotonin reuptake inhibitors (SSRIs) including sertraline, fluoxetine, and paroxetine can interact with numerous medications. Key interactions include: MAO inhibitors (contraindicated - life threatening serotonin syndrome), triptans (serotonin syndrome risk), anticoagulants (increased bleeding risk via platelet inhibition), and NSAIDs (additive GI bleeding risk). A 14-day washout period is required when switching between SSRIs and MAOIs.');

INSERT INTO CLINICAL_GUIDELINES (SOURCE, TITLE, CONTENT)
VALUES
    ('Migraine Treatment Protocol',
     'Triptan Prescribing Guidelines for Patients on Serotonergic Medications',
     'When prescribing triptans for migraine, verify patient is not taking serotonergic medications. Alternative treatments for patients on SSRIs include: gepants (ubrogepant, rimegepant), NSAIDs, or combination acetaminophen/caffeine. If triptan use is clinically necessary in a patient on an SSRI, use the lowest effective dose and monitor closely for serotonin syndrome symptoms for 24 hours.');

INSERT INTO CLINICAL_GUIDELINES (SOURCE, TITLE, CONTENT)
VALUES
    ('FDA Drug Safety Communication',
     'Anticoagulant-NSAID Interaction Warning',
     'Concurrent use of anticoagulants (warfarin, heparin, direct oral anticoagulants) with NSAIDs (ibuprofen, naproxen, aspirin) significantly increases the risk of gastrointestinal and other bleeding events. NSAIDs inhibit platelet function and can cause gastric mucosal damage, compounding the bleeding risk from anticoagulation. Recommend acetaminophen as first-line analgesic for patients on anticoagulants. If NSAID use is unavoidable, co-prescribe a proton pump inhibitor and monitor INR closely.');

INSERT INTO CLINICAL_GUIDELINES (SOURCE, TITLE, CONTENT)
VALUES
    ('ACC/AHA Clinical Guidelines',
     'Anticoagulation Management in Atrial Fibrillation',
     'Patients with atrial fibrillation on chronic anticoagulation therapy require careful medication management. Avoid concurrent NSAIDs, monitor for drug interactions with new prescriptions. Warfarin patients should maintain stable vitamin K intake and have regular INR monitoring. When adding new medications, check for CYP2C9 and CYP3A4 interactions that may potentiate or reduce anticoagulant effect.');

-- ============================================================
-- STEP 7: Generate embeddings for clinical guidelines
-- This uses Cortex AI to create vector embeddings for RAG search
-- ============================================================
UPDATE CLINICAL_GUIDELINES
SET EMBEDDING = SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', CONTENT)
WHERE EMBEDDING IS NULL;

-- ============================================================
-- STEP 8: Verify everything is set up correctly
-- ============================================================
SELECT 'PATIENT_DATA' AS TABLE_NAME, COUNT(*) AS ROW_COUNT FROM PATIENT_DATA
UNION ALL
SELECT 'PATIENT_MEDICATIONS', COUNT(*) FROM PATIENT_MEDICATIONS
UNION ALL
SELECT 'PATIENT_ALLERGIES', COUNT(*) FROM PATIENT_ALLERGIES
UNION ALL
SELECT 'CLINICAL_GUIDELINES', COUNT(*) FROM CLINICAL_GUIDELINES;

-- Verify embeddings were generated
SELECT ID, TITLE, EMBEDDING IS NOT NULL AS HAS_EMBEDDING FROM CLINICAL_GUIDELINES;

-- Test Cortex AI_COMPLETE is working
SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-3-5-sonnet', 'Say hello in one sentence') AS TEST_RESPONSE;

-- Test vector search is working
SELECT TITLE, VECTOR_COSINE_SIMILARITY(
    EMBEDDING,
    SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', 'serotonin syndrome triptan SSRI interaction')
) AS RELEVANCE
FROM CLINICAL_GUIDELINES
ORDER BY RELEVANCE DESC
LIMIT 3;
