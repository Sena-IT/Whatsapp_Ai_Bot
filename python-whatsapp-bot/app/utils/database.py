import os
import psycopg2
import logging
from datetime import datetime
from dotenv import load_dotenv, find_dotenv
import json

# Load Environment Variables
dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

# Database Connection
db_conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=os.getenv('DB_PORT'),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)

# ===========================
# ✅ Client Operations
# ===========================
def insert_client(data, phone_number):
    """
    Insert client data into the clients table.
    """
    cursor = None
    try:
        # Validate required fields
        if not data.get('name'):
            logging.error("❌ Client name is required")
            return False
            
        query = """
            INSERT INTO clients (name, aadhar_number, phone_number, authorized_phone_numbers, 
            aadhar_verified, phone_number_verified, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (phone_number) DO UPDATE 
            SET name = EXCLUDED.name,
                aadhar_number = EXCLUDED.aadhar_number,
                authorized_phone_numbers = EXCLUDED.authorized_phone_numbers,
                aadhar_verified = EXCLUDED.aadhar_verified,
                phone_number_verified = EXCLUDED.phone_number_verified
            RETURNING client_id
        """
        
        values = (
            data.get('name'),
            data.get('aadhar_number'),
            phone_number,
            json.dumps(data.get('authorized_phone_numbers', [])),
            data.get('aadhar_verified', False),
            data.get('phone_number_verified', False)
        )
        
        cursor = db_conn.cursor()
        cursor.execute(query, values)
        client_id = cursor.fetchone()[0]
        db_conn.commit()
        logging.info("✅ Client inserted/updated successfully with ID: %s", client_id)
        return True
        
    except psycopg2.Error as e:
        if db_conn:
            db_conn.rollback()
        logging.error("❌ Error inserting client: %s", e)
        return False
        
    finally:
        if cursor:
            cursor.close()


def get_client_by_phone(phone_number):
    """
    Fetch client details by phone number.
    """
    query = """
        SELECT client_id, name, aadhar_number, phone_number, authorized_phone_numbers
        FROM clients
        WHERE phone_number = %s
    """
    with db_conn.cursor() as cursor:
        cursor.execute(query, (phone_number,))
        result = cursor.fetchone()
        if result:
            return {
                "client_id": result[0],
                "name": result[1],
                "aadhar_number": result[2],
                "phone_number": result[3],
                "authorized_phone_numbers": result[4]
            }
        return None


# ===========================
# ✅ SRN Operations
# ===========================
def insert_srn(session_data, phone_number):
    """
    Insert SRN data into srns table.
    """
    cursor = None
    try:
        # # First ensure client insertion was successful
        # if not insert_client(session_data, phone_number):
        #     logging.error("❌ Failed to insert/update client data")
        #     return
            
        # Get client_id
        client = get_client_by_phone(phone_number)
        print("------------insert srn---- client ---------", client)
        if not client:
            logging.error("❌ Client not found for phone number: %s", phone_number)
            return
            
        client_id = client['client_id']
        
        cursor = db_conn.cursor()
        
        # Fetch the service_id based on the service_name
        service_name = session_data.get('service', 'GST')  # Default to GST if not specified
        service_id_query = "SELECT service_id FROM service WHERE service_name = %s"
        cursor.execute(service_id_query, (service_name,))
        service_id_result = cursor.fetchone()

        print("session data insert srn",session_data)
        
        if not service_id_result:
            logging.error("❌ Service ID not found for service_name '%s'.", service_name)
            return
            
        service_id = service_id_result[0]
        
        # Insert SRN data with default values where needed
        query = """
            INSERT INTO srn (client_id, service_id, due_date, task_type, status, 
            payment_status, service_specific_data, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """
        values = (
            client_id,
            service_id,
            session_data.get('due_date', None),
            session_data.get('task_type', "non-recurring"),
            session_data.get('status' , "pending"),
            session_data.get('payment_status','unpaid'),
            json.dumps(session_data.get('service_specific_data', {}))
        )
        
        cursor.execute(query, values)
        db_conn.commit()
                
        if cursor.rowcount > 0:
            logging.info("✅ SRN inserted successfully.")
            status_code = 201  # Created
        else:
            logging.warning("⚠️ No rows affected.")
            status_code = 400  # Bad Request (or relevant code)
            logging.info("✅ SRN inserted successfully.")
        return status_code
                
    except Exception as e:
        if db_conn:
            db_conn.rollback()
        logging.error("❌ Error inserting SRN: %s", str(e))
        
    finally:
        if cursor:
            cursor.close()


def get_srn_by_client(client_id):
    """
    Fetch all SRNs for a client.
    """
    query = """
        SELECT srn_id, service_id, due_date, task_type, status, payment_status
        FROM srns
        WHERE client_id = %s
    """
    with db_conn.cursor() as cursor:
        cursor.execute(query, (client_id,))
        results = cursor.fetchall()
        return [
            {
                "srn_id": row[0],
                "service_id": row[1],
                "due_date": row[2],
                "task_type": row[3],
                "status": row[4],
                "payment_status": row[5]
            }
            for row in results
        ]


# ===========================
# ✅ Payment Operations
# ===========================
def insert_payment(data):
    """
    Insert payment data into payments table.
    """
    query = """
        INSERT INTO payments (client_id, srn_id, amount, payment_method, 
        payment_status, transaction_id, paid_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """
    values = (
        data.get('client_id'),
        data.get('srn_id'),
        data.get('amount'),
        data.get('payment_method'),
        data.get('payment_status'),
        data.get('transaction_id')
    )
    
    with db_conn.cursor() as cursor:
        cursor.execute(query, values)
        db_conn.commit()
        logging.info("✅ Payment inserted successfully.")


# ===========================
# ✅ Service Operations
# ===========================
def insert_service(data):
    """
    Insert service data into services table.
    """
    query = """
        INSERT INTO services (service_name, description, sub_services, created_at)
        VALUES (%s, %s, %s, NOW())
    """
    values = (
        data.get('service_name'),
        data.get('description'),
        json.dumps(data.get('sub_services'))
    )
    
    with db_conn.cursor() as cursor:
        cursor.execute(query, values)
        db_conn.commit()
        logging.info("✅ Service inserted successfully.")


# ===========================
# ✅ Close DB Connection
# ===========================
def close_db_connection():
    db_conn.close()


import atexit
atexit.register(close_db_connection)
