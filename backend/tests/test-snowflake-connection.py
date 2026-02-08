import os
from snowflake.connector import connect
from dotenv import load_dotenv

# Load your .env file
load_dotenv()

def test_connection():
    print("Attempting to connect to Snowflake...")
    
    try:
        # Establish Connection
        conn = connect(
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            warehouse="COMPUTE_WH",
            database="SYNAPSE_DB",
            schema="PUBLIC"
        )
        print("Connection Established!")

        # Test a Basic Query
        cursor = conn.cursor()
        cursor.execute("SELECT CURRENT_VERSION()")
        version = cursor.fetchone()[0]
        print(f"Snowflake Version: {version}")

        # Test Your Specific Database (Kevin Patel)
        cursor.execute("SELECT COUNT(*) FROM PATIENT_DATA")
        count = cursor.fetchone()[0]
        print(f"Patient Count: {count}")

        if count > 0:
            print("\nSUCCESS! Your Python backend is ready to go.")
        else:
            print("\nConnection worked, but PATIENT_DATA table is empty.")

    except Exception as e:
        print("\nCONNECTION FAILED")
        print("Error details:", e)
        print("\nCheck your .env file:")
        print(f"Account: {os.getenv('SNOWFLAKE_ACCOUNT')}")
        print(f"User: {os.getenv('SNOWFLAKE_USER')}")

if __name__ == "__main__":
    test_connection()