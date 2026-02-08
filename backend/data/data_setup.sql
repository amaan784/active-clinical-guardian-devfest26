-- ============================================================
-- Snowflake Setup Script
-- Run this entire script in a Snowflake SQL Worksheet
-- ============================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE SYNAPSE_DB;
USE SCHEMA PUBLIC;
USE WAREHOUSE COMPUTE_WH;

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

-- A. Standard Safety Warnings
INSERT INTO CLINICAL_GUIDELINES (SOURCE, TITLE, CONTENT)
VALUES 
    ('FDA Drug Safety', 'Serotonin Syndrome - Triptans + SSRIs', 
     'Concurrent use of triptans (sumatriptan, rizatriptan) with SSRIs (sertraline, fluoxetine) may result in life-threatening serotonin syndrome. Symptoms: agitation, rapid heartbeat, fever, muscle rigidity, and coordination loss.'),
    
    ('Clinical Pharmacology', 'SSRI Drug Interactions', 
     'SSRIs (sertraline, fluoxetine) interact with: MAO inhibitors, triptans (serotonin risk), anticoagulants (bleeding risk), and NSAIDs (GI bleeding risk).'),
    
    ('FDA Drug Safety', 'Anticoagulant + NSAID Warning', 
     'Concurrent use of anticoagulants (warfarin) with NSAIDs (ibuprofen, naproxen, aspirin) significantly increases risk of GI bleeding. Recommend Acetaminophen (Tylenol) as first-line analgesic.');

-- B. FDA Specific Label Data (Zoloft)
INSERT INTO CLINICAL_GUIDELINES (SOURCE, TITLE, CONTENT)
VALUES 
    ('FDA Zoloft Label', 'Zoloft Serotonin Warning', 
     'Serotonin Syndrome reported with Zoloft, particularly with concomitant use of triptans, fentanyl, and St. John''s Wort. Monitor for mental status changes and autonomic instability.'),
    
    ('FDA Zoloft Label', 'Zoloft Bleeding Warning', 
     'Increased bleeding risk with Zoloft. Concomitant use of aspirin, NSAIDs, warfarin, and other anticoagulants may add to this risk. Range from ecchymoses to life-threatening hemorrhages.');

-- C. General Knowledge (Drug Classes & Symptoms)
INSERT INTO CLINICAL_GUIDELINES (SOURCE, TITLE, CONTENT)
VALUES 
    ('NLM Drug Classes', 'SSRI List', 
     'SSRI Class includes: Sertraline (Zoloft), Fluoxetine (Prozac), Citalopram (Celexa), Escitalopram (Lexapro). All share interaction profiles.'),
    
    ('NLM Drug Classes', 'Triptan List', 
     'Triptan Class includes: Sumatriptan (Imitrex), Rizatriptan (Maxalt), Zolmitriptan (Zomig). Used for migraine.'),
    
    ('Clinical Ref', 'Serotonin Syndrome Symptoms', 
     'Key symptoms: Agitation, confusion, tachycardia, dilated pupils, muscle twitching/rigidity, heavy sweating, diarrhea.');

-- D. OTC Medication Logic (Safe vs Unsafe)
INSERT INTO CLINICAL_GUIDELINES (SOURCE, TITLE, CONTENT)
VALUES 
    ('OTC Safety', 'Ibuprofen (Advil/Motrin) Risk', 
     'Ibuprofen is an NSAID. DANGER: Significant GI bleeding risk when combined with SSRIs or Anticoagulants. Avoid in these patients.'),
    
    ('OTC Safety', 'Naproxen (Aleve) Risk', 
     'Naproxen is a long-acting NSAID. DANGER: Increases bleeding time. Contraindicated with SSRIs or Blood Thinners.'),
    
    ('OTC Safety', 'Acetaminophen (Tylenol) Safety', 
     'Acetaminophen (Tylenol) is not an NSAID. It is the SAFE preferred analgesic for patients on SSRIs or Blood Thinners.');
     
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
SELECT
  TITLE,
  VECTOR_COSINE_SIMILARITY(
    EMBEDDING,
    SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', 'serotonin syndrome triptan SSRI interaction')
  ) AS RELEVANCE
FROM CLINICAL_GUIDELINES
ORDER BY RELEVANCE DESC
LIMIT 3;
