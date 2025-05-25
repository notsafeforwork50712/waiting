import pyodbc
import os
import logging
from dotenv import load_dotenv
from datetime import datetime


load_dotenv()

DB_SERVER = os.getenv('DB_SERVER')
DB_NAME = os.getenv('DB_NAME')
DB_USERNAME = os.getenv('DB_USERNAME')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_TABLE = os.getenv('DB_TABLE') 
DB_KIOSK_TABLE = os.getenv('DB_KIOSK_TABLE')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_connection():
    """Creates and returns a connection to the SQL Server database."""
    conn_str = (
        r'DRIVER={ODBC Driver 18 for SQL Server};' # Updated to match installed driver
        r'SERVER=' + DB_SERVER + ';'
        r'DATABASE=' + DB_NAME + ';'
        r'UID=' + DB_USERNAME + ';'
        r'PWD=' + DB_PASSWORD + ';'
        r'Encrypt=Yes;' # Changed to Yes as per testing
        r'TrustServerCertificate=Yes;' # Add if self-signed cert or encryption without full validation ????
    )
    logging.info(f"Attempting to connect to database: {DB_SERVER}/{DB_NAME}")
    try:
        conn = pyodbc.connect(conn_str, autocommit=False) 
        logging.info("Database connection successful")
        return conn
    except Exception as e:
        logging.error(f"Database connection error: {str(e)}")
        # Consider how to handle this - maybe raise it or return None
        # For a web app, failing requests might be better than crashing
        return None # Or raise e ?? will figure out later 

def add_visitor(visitor_data):
    """Adds a new visitor record to the database."""
    conn = create_connection()
    if not conn:
        return False, "Database connection failed"

    cursor = conn.cursor()

    sql = f"""
        INSERT INTO {DB_TABLE} (
            GuestFirstName, GuestLastName, VisitorType, Branch, DepartmentVisited,
            VendorName, BadgeNumber, HostEmployeeName, Comments, CheckInTime, Status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), 'CheckedIn')
    """
    params = (
        visitor_data.get('GuestFirstName'),
        visitor_data.get('GuestLastName'),
        visitor_data.get('VisitorType'),
        visitor_data.get('Branch'),
        visitor_data.get('DepartmentVisited'),
        visitor_data.get('VendorName'),
        visitor_data.get('BadgeNumber'),
        visitor_data.get('HostEmployeeName'), # "Here to see"
        visitor_data.get('Comments')
    )

    try:
        logging.info(f"Executing SQL: {sql} with params: {params}")
        cursor.execute(sql, params)
        conn.commit() # Commit the transaction
        logging.info("Visitor added successfully.")
        return True, "Visitor added successfully."
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to add visitor. SQLSTATE: {sqlstate} Message: {message}")
        conn.rollback() # Rollback on error
        return False, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred: {str(e)}")
        conn.rollback()
        return False, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ==============================================================
# == NEW: Member Facing Check-In Database Functions           ==
# ==============================================================

def add_facing_member(details):
    """Adds a new record to the FacingMembers table."""
    conn = create_connection()
    if not conn:
        return None, "Database connection failed"

    cursor = conn.cursor()
    # Use environment variable for table name
    # Use environment variable for table name
    # Assumes the DB_KIOSK_TABLE has columns: SystemName, SystemAddress, SystemHomePhone, SystemEmail, SystemCellPhone
    sql = f"""
        INSERT INTO {DB_KIOSK_TABLE} (
            IsCurrentMember, HelpTopic, SubIssue, Name, Last4SSN, MemberNumber,
            HelpWithAccountTransaction, HelpWithFraud, HelpWithFundsTransfer, HelpWithLoanPayment,
            SubmittedBy, CreatedDate,
            SystemName, SystemAddress, SystemHomePhone, SystemEmail, SystemCellPhone, -- Added System fields from DNA lookup
            Status
        )
        OUTPUT INSERTED.FacingMemberID -- Get the newly created ID
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), ?, ?, ?, ?, ?, 'Waiting') -- Added placeholders for System fields and default Status
    """
    params = (
        details.get('IsCurrentMember', False), # Default to False if not provided
        details.get('HelpTopic'),
        details.get('SubIssue'),
        details.get('Name'), # Name entered by user
        details.get('Last4SSN'), # Last 4 entered by user
        details.get('MemberNumber'), # Member number entered by user
        details.get('HelpWithAccountTransaction', False),
        details.get('HelpWithFraud', False),
        details.get('HelpWithFundsTransfer', False),
        details.get('HelpWithLoanPayment', False),
        details.get('SubmittedBy'),
        # --- Get data fetched from DNA (passed in 'details' dict by app.py) ---
        details.get('full_name'), # Fetched from DNA, map to SystemName
        details.get('address'),   # Fetched from DNA, map to SystemAddress
        details.get('home_phone'),# Fetched from DNA, map to SystemHomePhone
        details.get('email'),     # Fetched from DNA, map to SystemEmail
        details.get('mobile_phone') # Fetched from DNA, map to SystemCellPhone
    )

    try:
        logging.info(f"Executing SQL for add_facing_member: {sql} with params: {params}")
        cursor.execute(sql, params)
        new_id = cursor.fetchone()[0] # Fetch the ID returned by OUTPUT
        conn.commit()
        logging.info(f"FacingMember record added successfully with ID: {new_id}.")
        return new_id, None # Return the new ID and no error
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to add FacingMember record. SQLSTATE: {sqlstate} Message: {message}")
        conn.rollback()
        return None, f"Database error: {message}" # Return None ID and error message
    except Exception as e:
        logging.error(f"An unexpected error occurred adding FacingMember: {str(e)}")
        conn.rollback()
        return None, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def update_facing_member_confirmation(facing_member_id, is_confirmed):
    """Updates the IsSystemInfoConfirmed flag for a FacingMembers record."""
    conn = create_connection()
    if not conn:
        return False, "Database connection failed"

    cursor = conn.cursor()
    # Use environment variable for table name
    sql = f"""
        UPDATE {DB_KIOSK_TABLE}
        SET IsSystemInfoConfirmed = ?
        WHERE FacingMemberID = ?
    """
    # Convert boolean to 1 or 0 for SQL Server BIT type
    params = (1 if is_confirmed else 0, facing_member_id)

    try:
        logging.info(f"Executing SQL for update_facing_member_confirmation: {sql} with params: {params}")
        cursor.execute(sql, params)
        if cursor.rowcount == 0:
            conn.rollback()
            logging.warning(f"FacingMember ID {facing_member_id} not found for confirmation update.")
            return False, "Record not found."
        conn.commit()
        logging.info(f"FacingMember ID {facing_member_id} confirmation updated successfully.")
        return True, None # Return success and no error
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to update FacingMember confirmation. SQLSTATE: {sqlstate} Message: {message}")
        conn.rollback()
        return False, f"Database error: {message}" # Return failure and error message
    except Exception as e:
        logging.error(f"An unexpected error occurred updating FacingMember confirmation: {str(e)}")
        conn.rollback()
        return False, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_facing_member_details(facing_member_id):
    """Retrieves details for a specific FacingMembers record by ID."""
    conn = create_connection()
    if not conn:
        return None, "Database connection failed"

    cursor = conn.cursor()
    # Use environment variable for table name
    sql = f"""
        SELECT *
        FROM {DB_KIOSK_TABLE}
        WHERE FacingMemberID = ?
    """
    params = (facing_member_id,)

    try:
        logging.info(f"Executing SQL for get_facing_member_details with ID: {facing_member_id}")
        cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        row = cursor.fetchone()
        if row:
            details = dict(zip(columns, row))
            logging.info(f"Retrieved details for FacingMember ID: {facing_member_id}")
            return details, None # Return details dictionary and no error
        else:
            logging.warning(f"No FacingMember found with ID: {facing_member_id}")
            return None, "Record not found" # Return None and error message
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to retrieve FacingMember details. SQLSTATE: {sqlstate} Message: {message}")
        return None, f"Database error: {message}" # Return None and error message
    except Exception as e:
        logging.error(f"An unexpected error occurred fetching FacingMember details: {str(e)}")
        return None, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# --- Kiosk Queue Functions ---

def get_kiosk_queue(status='Waiting'):
    """Retrieves FacingMembers records with a specific status (default 'Waiting'), ordered by CreatedDate."""
    conn = create_connection()
    if not conn:
        return [], "Database connection failed"

    cursor = conn.cursor()
    members = []
    # Use environment variable for table name
    # ASSUMES a 'Status' column exists in FacingMembers table
    
    # Log the actual query for debugging
    logging.info(f"DB_KIOSK_TABLE value: {DB_KIOSK_TABLE}")
    
    # Modified query with proper status handling:
    # - For 'Waiting': Get records with Status='Waiting' OR Status IS NULL
    # - For other statuses (like 'Handled'): Only get exact matches
    if status.upper() == 'WAITING':
        sql = f"""
            SELECT
                FacingMemberID, Name, HelpTopic, SubIssue, CreatedDate, Status, MemberNumber
            FROM {DB_KIOSK_TABLE}
            WHERE UPPER(Status) = 'WAITING' OR Status IS NULL
            ORDER BY CreatedDate ASC -- Show oldest waiting first
        """
        params = ()
    else:
        sql = f"""
            SELECT
                FacingMemberID, Name, HelpTopic, SubIssue, CreatedDate, Status
            FROM {DB_KIOSK_TABLE}
            WHERE UPPER(Status) = UPPER(?)
            ORDER BY CreatedDate DESC -- Show most recently handled first
        """
        params = (status,)
    try:
        logging.info(f"Executing SQL for get_kiosk_queue with status: {status}")
        cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        members = [dict(zip(columns, row)) for row in cursor.fetchall()]
        logging.info(f"Retrieved {len(members)} kiosk queue records with status '{status}'.")
        return members, None
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        # Check if the error is due to an invalid column name ('Status')
        if 'Invalid column name' in message and 'Status' in message:
             logging.error("CRITICAL: 'Status' column not found in [Interactions].[dbo].[FacingMembers] table. Queue functionality requires this column.")
             return [], "Database schema error: 'Status' column missing."
        else:
            logging.error(f"Failed to retrieve kiosk queue. SQLSTATE: {sqlstate} Message: {message}")
            return [], f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching kiosk queue: {str(e)}")
        return [], f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_kiosk_queue_count(status='Waiting'):
    """Returns the count of FacingMembers with a specific status (default 'Waiting')."""
    conn = create_connection()
    if not conn:
        return 0, "Database connection failed"

    cursor = conn.cursor()
    # Use environment variable for table name
    # ASSUMES a 'Status' column exists
    
    # Modified query to be more flexible with status matching (case-insensitive)
    sql = f"""
        SELECT COUNT(*) AS QueueCount
        FROM {DB_KIOSK_TABLE}
        WHERE UPPER(Status) = UPPER(?) OR Status IS NULL
    """
    params = (status,)
    try:
        logging.info(f"Executing SQL for get_kiosk_queue_count with status: {status}")
        cursor.execute(sql, params)
        count = cursor.fetchone()[0]
        logging.info(f"Kiosk queue count for status '{status}': {count}")
        return count, None
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        if 'Invalid column name' in message and 'Status' in message:
             logging.error("CRITICAL: 'Status' column not found in [Interactions].[dbo].[FacingMembers] table.")
             return 0, "Database schema error: 'Status' column missing."
        else:
            logging.error(f"Failed to get kiosk queue count. SQLSTATE: {sqlstate} Message: {message}")
            return 0, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred while getting kiosk queue count: {str(e)}")
        return 0, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def update_kiosk_queue_status(facing_member_id, new_status='Handled'):
    """Updates the Status for a FacingMembers record."""
    conn = create_connection()
    if not conn:
        return False, "Database connection failed"

    cursor = conn.cursor()
    # Use environment variable for table name
    # ASSUMES a 'Status' column exists
    
    # Modified query to be more flexible with status matching
    sql = f"""
        UPDATE {DB_KIOSK_TABLE}
        SET Status = ?
        WHERE FacingMemberID = ? 
    """
    params = (new_status, facing_member_id)

    try:
        logging.info(f"Executing SQL for update_kiosk_queue_status: ID={facing_member_id}, NewStatus={new_status}")
        cursor.execute(sql, params)
        if cursor.rowcount == 0:
            conn.rollback()
            # Could be already handled or invalid ID
            logging.warning(f"Kiosk Queue record ID {facing_member_id} not found for update.")
            return False, "Record not found."
        conn.commit()
        logging.info(f"Kiosk Queue record ID {facing_member_id} status updated to '{new_status}'.")
        return True, None # Return success and no error
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        conn.rollback()
        if 'Invalid column name' in message and 'Status' in message:
             logging.error("CRITICAL: 'Status' column not found in [Interactions].[dbo].[FacingMembers] table.")
             return False, "Database schema error: 'Status' column missing."
        else:
            logging.error(f"Failed to update kiosk queue status. SQLSTATE: {sqlstate} Message: {message}")
            return False, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred updating kiosk queue status: {str(e)}")
        conn.rollback()
        return False, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# --- End Kiosk Queue Functions ---


def get_current_visitor_count():
    """Returns the count of visitors currently checked in."""
    conn = create_connection()
    if not conn:
        return 0, "Database connection failed"

    cursor = conn.cursor()
    sql = f"""
        SELECT COUNT(*) AS CurrentVisitors
        FROM {DB_TABLE}
        WHERE Status = 'CheckedIn'
    """
    try:
        cursor.execute(sql)
        count = cursor.fetchone()[0]
        logging.info(f"Current visitor count: {count}")
        return count, None
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to get visitor count. SQLSTATE: {sqlstate} Message: {message}")
        return 0, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred while getting visitor count: {str(e)}")
        return 0, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
def get_checked_in_badges():
    """Returns a list of badge numbers that are currently checked in."""
    conn = create_connection()
    if not conn:
        return [], "Database connection failed"

    cursor = conn.cursor()
    sql = f"""
        SELECT BadgeNumber
        FROM {DB_TABLE}
        WHERE Status = 'CheckedIn'
    """
    try:
        cursor.execute(sql)
        badges = [row[0] for row in cursor.fetchall()]
        logging.info(f"Retrieved {len(badges)} checked-in badges")
        return badges, None
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to get checked-in badges. SQLSTATE: {sqlstate} Message: {message}")
        return [], f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred while getting checked-in badges: {str(e)}")
        return [], f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_all_visitors():
    """Retrieves all visitor records (excluding pending visitors), ordered by CheckInTime descending."""
    conn = create_connection()
    if not conn:
        return None, "Database connection failed"

    cursor = conn.cursor()
    visitors = []
    sql = f"""
        SELECT
            VisitorID, GuestFirstName, GuestLastName, VisitorType, Branch, DepartmentVisited,
            VendorName, BadgeNumber, HostEmployeeName, Comments,
            CheckInTime, CheckOutTime, Status
        FROM {DB_TABLE}
        WHERE Status != 'Pending' AND (Cancel = 0 OR Cancel IS NULL)
        ORDER BY CheckInTime DESC
    """
    try:
        cursor.execute(sql)
        # Get column names from cursor description
        columns = [column[0] for column in cursor.description]
        # Fetch rows and convert to list of dictionaries
        visitors = [dict(zip(columns, row)) for row in cursor.fetchall()]
        logging.info(f"Retrieved {len(visitors)} visitor records.")
        return visitors, None
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to retrieve visitors. SQLSTATE: {sqlstate} Message: {message}")
        return None, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching visitors: {str(e)}")
        return None, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_visitors_by_date_range(start_date, end_date):
    """Retrieves visitor records within a specified date range."""
    conn = create_connection()
    if not conn:
        return None, "Database connection failed"

    cursor = conn.cursor()
    visitors = []
    sql = f"""
        SELECT
            VisitorID, GuestFirstName, GuestLastName, VisitorType, Branch, DepartmentVisited,
            VendorName, BadgeNumber, HostEmployeeName, Comments,
            CheckInTime, CheckOutTime, Status, ColleagueFirstName, ColleagueLastName,
            AdvanceCheckInTime, SubmissionTime, IsAdvanceCheckIn, SubmitterIPAddress, Cancel
        FROM {DB_TABLE}
        WHERE CheckInTime BETWEEN ? AND ?
        ORDER BY CheckInTime DESC
    """
    params = (start_date, end_date)
    
    try:
        cursor.execute(sql, params)
        # Get column names from cursor description
        columns = [column[0] for column in cursor.description]
        # Fetch rows and convert to list of dictionaries
        visitors = [dict(zip(columns, row)) for row in cursor.fetchall()]
        logging.info(f"Retrieved {len(visitors)} visitor records between {start_date} and {end_date}.")
        return visitors, None
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to retrieve visitors by date range. SQLSTATE: {sqlstate} Message: {message}")
        return None, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching visitors by date range: {str(e)}")
        return None, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def checkout_visitor(visitor_id):
    """Updates a visitor's status to 'CheckedOut' and sets the CheckOutTime."""
    conn = create_connection()
    if not conn:
        return False, "Database connection failed"

    cursor = conn.cursor()
    sql = f"""
        UPDATE {DB_TABLE}
        SET Status = 'CheckedOut', CheckOutTime = GETDATE()
        WHERE VisitorID = ? AND Status = 'CheckedIn'
    """
    params = (visitor_id,)

    try:
        logging.info(f"Checking out visitor ID: {visitor_id}")
        cursor.execute(sql, params)
        # Check if any row was actually updated
        if cursor.rowcount == 0:
            conn.rollback() # Rollback if no rows affected (already checked out or invalid ID)
            logging.warning(f"Visitor ID {visitor_id} not found or already checked out.")
            return False, "Visitor not found or already checked out."

        conn.commit() # Commit the transaction
        logging.info(f"Visitor ID {visitor_id} checked out successfully.")
        return True, "Visitor checked out successfully."
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to check out visitor ID {visitor_id}. SQLSTATE: {sqlstate} Message: {message}")
        conn.rollback() # Rollback on error
        return False, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred during checkout: {str(e)}")
        conn.rollback()
        return False, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def add_advanced_visitor(visitor_data):
    """Adds a new advanced check-in visitor record to the database."""
    conn = create_connection()
    if not conn:
        return False, "Database connection failed"

    cursor = conn.cursor()

    # Convert the advance check-in time from string to datetime
    try:
        advance_checkin_time = datetime.fromisoformat(visitor_data.get('AdvanceCheckInTime').replace('Z', '+00:00'))
    except (ValueError, AttributeError) as e:
        logging.error(f"Invalid advance check-in time format: {e}")
        return False, f"Invalid advance check-in time format: {e}"

    sql = f"""
        INSERT INTO {DB_TABLE} (
            GuestFirstName, GuestLastName, VisitorType, Branch, DepartmentVisited,
            VendorName, BadgeNumber, HostEmployeeName, Comments, 
            ColleagueFirstName, ColleagueLastName, AdvanceCheckInTime,
            SubmissionTime, IsAdvanceCheckIn, SubmitterIPAddress, Status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), ?, ?, 'Pending')
    """
    params = (
        visitor_data.get('GuestFirstName'),
        visitor_data.get('GuestLastName'),
        visitor_data.get('VisitorType'),
        visitor_data.get('Branch'),
        visitor_data.get('DepartmentVisited'),
        visitor_data.get('VendorName'),
        visitor_data.get('BadgeNumber'),
        visitor_data.get('HostEmployeeName'),
        visitor_data.get('Comments'),
        visitor_data.get('ColleagueFirstName'),
        visitor_data.get('ColleagueLastName'),
        advance_checkin_time,
        visitor_data.get('IsAdvanceCheckIn', True),
        visitor_data.get('SubmitterIPAddress')
    )

    try:
        logging.info(f"Executing SQL for advanced check-in: {sql} with params: {params}")
        cursor.execute(sql, params)
        conn.commit() # Commit the transaction
        logging.info("Advanced check-in visitor added successfully.")
        return True, "Advanced check-in visitor added successfully."
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to add advanced check-in visitor. SQLSTATE: {sqlstate} Message: {message}")
        conn.rollback() # Rollback on error
        return False, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred: {str(e)}")
        conn.rollback()
        return False, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_pending_visitors():
    """Retrieves all pending (pre-registered) visitor records, ordered by AdvanceCheckInTime."""
    conn = create_connection()
    if not conn:
        return None, "Database connection failed"

    cursor = conn.cursor()
    visitors = []
    sql = f"""
        SELECT
            VisitorID, GuestFirstName, GuestLastName, VisitorType, Branch, DepartmentVisited,
            VendorName, BadgeNumber, HostEmployeeName, Comments,
            AdvanceCheckInTime, SubmissionTime, ColleagueFirstName, ColleagueLastName, Status
        FROM {DB_TABLE}
        WHERE Status = 'Pending' AND (Cancel = 0 OR Cancel IS NULL)
        ORDER BY AdvanceCheckInTime ASC
    """
    try:
        cursor.execute(sql)
        # Get column names from cursor description
        columns = [column[0] for column in cursor.description]
        # Fetch rows and convert to list of dictionaries
        visitors = [dict(zip(columns, row)) for row in cursor.fetchall()]
        logging.info(f"Retrieved {len(visitors)} pending visitor records.")
        return visitors, None
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to retrieve pending visitors. SQLSTATE: {sqlstate} Message: {message}")
        return None, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching pending visitors: {str(e)}")
        return None, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_visitor_details(visitor_id):
    """Retrieves details for a specific visitor by ID."""
    conn = create_connection()
    if not conn:
        return None, "Database connection failed"

    cursor = conn.cursor()
    sql = f"""
        SELECT
            VisitorID, GuestFirstName, GuestLastName, VisitorType, Branch, DepartmentVisited,
            VendorName, BadgeNumber, HostEmployeeName, Comments,
            CheckInTime, CheckOutTime, Status, ColleagueFirstName, ColleagueLastName,
            AdvanceCheckInTime, SubmissionTime, IsAdvanceCheckIn, SubmitterIPAddress, Cancel
        FROM {DB_TABLE}
        WHERE VisitorID = ?
    """
    params = (visitor_id,)
    
    try:
        cursor.execute(sql, params)
        # Get column names from cursor description
        columns = [column[0] for column in cursor.description]
        # Fetch the row and convert to dictionary
        row = cursor.fetchone()
        if row:
            visitor = dict(zip(columns, row))
            logging.info(f"Retrieved details for visitor ID: {visitor_id}")
            return visitor, None
        else:
            logging.warning(f"No visitor found with ID: {visitor_id}")
            return None, "Visitor not found"
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to retrieve visitor details. SQLSTATE: {sqlstate} Message: {message}")
        return None, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching visitor details: {str(e)}")
        return None, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def checkin_pending_visitor(visitor_id, badge_number):
    """Updates a pending visitor's status to 'CheckedIn', sets the CheckInTime, and assigns a badge."""
    conn = create_connection()
    if not conn:
        return False, "Database connection failed"

    cursor = conn.cursor()
    sql = f"""
        UPDATE {DB_TABLE}
        SET Status = 'CheckedIn', CheckInTime = GETDATE(), BadgeNumber = ?
        WHERE VisitorID = ? AND Status = 'Pending'
    """
    params = (badge_number, visitor_id)

    try:
        logging.info(f"Checking in pending visitor ID: {visitor_id} with badge: {badge_number}")
        cursor.execute(sql, params)
        # Check if any row was actually updated
        if cursor.rowcount == 0:
            conn.rollback() # Rollback if no rows affected
            logging.warning(f"Pending visitor ID {visitor_id} not found or already checked in.")
            return False, "Visitor not found or already checked in."

        conn.commit() # Commit the transaction
        logging.info(f"Pending visitor ID {visitor_id} checked in successfully.")
        return True, "Visitor checked in successfully."
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to check in pending visitor ID {visitor_id}. SQLSTATE: {sqlstate} Message: {message}")
        conn.rollback() # Rollback on error
        return False, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred during check-in: {str(e)}")
        conn.rollback()
        return False, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def cancel_visitor(visitor_id):
    """Sets a visitor's Cancel field to 1."""
    conn = create_connection()
    if not conn:
        return False, "Database connection failed"

    cursor = conn.cursor()
    sql = f"""
        UPDATE {DB_TABLE}
        SET Cancel = 1
        WHERE VisitorID = ? AND Status = 'Pending'
    """
    params = (visitor_id,)

    try:
        logging.info(f"Canceling visitor ID: {visitor_id}")
        cursor.execute(sql, params)
        # Check if any row was actually updated
        if cursor.rowcount == 0:
            conn.rollback() # Rollback if no rows affected
            logging.warning(f"Visitor ID {visitor_id} not found or not in Pending status.")
            return False, "Visitor not found or not in Pending status."

        conn.commit() # Commit the transaction
        logging.info(f"Visitor ID {visitor_id} canceled successfully.")
        return True, "Visitor canceled successfully."
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        message = ex.args[1]
        logging.error(f"Failed to cancel visitor ID {visitor_id}. SQLSTATE: {sqlstate} Message: {message}")
        conn.rollback() # Rollback on error
        return False, f"Database error: {message}"
    except Exception as e:
        logging.error(f"An unexpected error occurred during cancellation: {str(e)}")
        conn.rollback()
        return False, f"An unexpected error occurred: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
