# waiting/app.py - Kiosk Queue Management Application
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import logging
from logging.handlers import RotatingFileHandler
import html 
from dotenv import load_dotenv
from datetime import datetime, timedelta
import threading
from cachetools import TTLCache

load_dotenv()

# Import database functions
import database

# Import DNA API Client
try:
    from dna_client import DNAApiClient, DNAApiError
    DNA_CLIENT_AVAILABLE = True
    logging.info("Successfully imported DNAApiClient.")
except ImportError:
    logging.error("CRITICAL: Could not import dna_client.py. DNA API features will be disabled.")
    DNAApiClient = None
    DNAApiError = Exception
    DNA_CLIENT_AVAILABLE = False
except Exception as e:
    logging.error(f"CRITICAL: Error importing DNAApiClient: {e}", exc_info=True)
    DNAApiClient = None
    DNAApiError = Exception
    DNA_CLIENT_AVAILABLE = False

# Import MeridianLink API Client
try:
    from meridian_link_client import MeridianLinkClient, MeridianLinkError
    ML_CLIENT_AVAILABLE = True
    logging.info("Successfully imported MeridianLinkClient.")
except ImportError:
    logging.error("CRITICAL: Could not import meridian_link_client.py. MeridianLink API features will be disabled.")
    MeridianLinkClient = None
    MeridianLinkError = Exception
    ML_CLIENT_AVAILABLE = False
except Exception as e:
    logging.error(f"CRITICAL: Error importing MeridianLinkClient: {e}", exc_info=True)
    MeridianLinkClient = None
    MeridianLinkError = Exception
    ML_CLIENT_AVAILABLE = False

# Initialize Flask App
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'fallback_secret_key_please_change')
app.config['DEBUG'] = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')

# --- Configure File Logging ---
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_file = os.path.join(log_dir, 'waiting_app.log')
file_handler = logging.handlers.RotatingFileHandler(
    log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
)
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(log_formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(file_handler)

# Silence noisy libraries
logging.getLogger("msal").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ─── CACHES ────────────────────────────────────────────────────────────────────
dna_cache = TTLCache(maxsize=200, ttl=3600)   # 1 hr
transaction_cache = TTLCache(maxsize=500, ttl=600)   # 10 min
insight_cache = TTLCache(maxsize=100, ttl=600)   # 10 min

# Configuration for insights
INSIGHTS_TRANSACTION_DAYS = int(os.getenv('INSIGHTS_TRANSACTION_DAYS', 30))

def filter_recent_transactions(transactions, days=30):
    """Filter transactions to only include those from the last N days."""
    if not transactions:
        return []
    
    cutoff_date = datetime.now() - timedelta(days=days)
    recent_transactions = []
    
    for tx in transactions:
        tx_date_str = tx.get('date', '')
        if tx_date_str:
            try:
                # Try to parse the date (adjust format as needed based on your DNA API)
                tx_date = datetime.strptime(tx_date_str, '%Y-%m-%d')
                if tx_date >= cutoff_date:
                    recent_transactions.append(tx)
            except ValueError:
                # If date parsing fails, include the transaction to be safe
                recent_transactions.append(tx)
        else:
            # If no date, include the transaction
            recent_transactions.append(tx)
    
    return recent_transactions

# --- Initialize DNA Client ---
dna_client = None
if DNA_CLIENT_AVAILABLE:
    logger = logging.getLogger(__name__)
    try:
        dna_verify_ssl = os.getenv('DNA_VERIFY_SSL', 'false').lower() == 'true'
        logger.info("Attempting to initialize DNAApiClient...")
        dna_client = DNAApiClient(logger=logger, verify_ssl=dna_verify_ssl)
        logger.info(f"DNAApiClient object created successfully (Verify SSL: {dna_verify_ssl}).")
    except (ValueError, DNAApiError, Exception) as e:
        logger.error(f"Failed to initialize DNAApiClient: {e}", exc_info=True)
        dna_client = None

# --- Initialize MeridianLink Client ---
ml_client = None
if ML_CLIENT_AVAILABLE:
    logger = logging.getLogger(__name__)
    try:
        ml_verify_ssl = os.getenv('ML_VERIFY_SSL', 'false').lower() == 'true'
        logger.info("Attempting to initialize MeridianLinkClient...")
        ml_client = MeridianLinkClient(logger=logger, verify_ssl=ml_verify_ssl)
        logger.info(f"MeridianLinkClient object created successfully (Verify SSL: {ml_verify_ssl}).")
    except (MeridianLinkError, Exception) as e:
        logger.error(f"Failed to initialize MeridianLinkClient: {e}", exc_info=True)
        ml_client = None

# --- Context Processors ---
@app.context_processor
def inject_now():
    """Inject current UTC time."""
    return {'now': datetime.now(datetime.UTC) if hasattr(datetime, 'UTC') else datetime.utcnow()}

@app.context_processor
def inject_visitor_count():
    """Inject the current visitor count."""
    count = 0
    try:
        count, error = database.get_current_visitor_count()
        if error:
            logging.error(f"Error getting visitor count: {error}")
            count = 0
    except Exception as e:
        logging.error(f"Exception in inject_visitor_count: {e}", exc_info=True)
        count = 0
    return {'current_visitor_count': count}

# --- Routes ---
@app.route('/')
def index():
    """Landing page showing new dashboard."""
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    """Main dashboard with new UI - replaces kiosk queue as primary interface."""
    waiting_list = []
    handled_list = []
    waiting_count = 0
    db_error_waiting = None
    db_error_handled = None

    try:
        # Fetch waiting kiosk check-ins
        waiting_list_result, error_waiting = database.get_kiosk_queue(status='Waiting')
        if error_waiting:
            logging.error(f"[Dashboard] Error fetching waiting check-ins: {error_waiting}")
            db_error_waiting = "Could not load waiting list."
        elif waiting_list_result:
            waiting_list = waiting_list_result

        # Fetch handled kiosk check-ins
        handled_list_result, error_handled = database.get_kiosk_queue(status='Handled')
        if error_handled:
            logging.error(f"[Dashboard] Error fetching handled check-ins: {error_handled}")
            db_error_handled = "Could not load handled list."
        elif handled_list_result:
            handled_list = handled_list_result

        # Fetch waiting count
        count, error_count = database.get_kiosk_queue_count(status='Waiting')
        if error_count:
            logging.error(f"[Dashboard] Error fetching waiting count: {error_count}")
            waiting_count = len(waiting_list)
        else:
            waiting_count = count

        # Start background pre-fetching for waiting members
        if waiting_list and dna_client:
            def prefetch_all_data_background():
                """Pre-fetch DNA data and transactions for members in a background thread."""
                global dna_cache, transaction_cache
                logging.info(f"[Dashboard Background] Starting DNA and transaction pre-fetch for {len(waiting_list)} members")
                for member in waiting_list:
                    member_number = member.get('MemberNumber')
                    if member_number:
                        try:
                            logging.info(f"[Dashboard Background] Pre-fetching DNA data for member {member_number}")
                            person_details = None
                            
                            if member_number in dna_cache:
                                person_details = dna_cache[member_number]
                                logging.info(f"[Dashboard Background] Using cached DNA data for member {member_number}")
                            else:
                                try:
                                    person_details = dna_client.get_person_detail_by_member_number(member_number)
                                    if person_details:
                                        dna_cache[member_number] = person_details
                                        logging.info(f"[Dashboard Background] Successfully pre-fetched DNA data for member {member_number}")
                                except AttributeError:
                                    person_number = dna_client.get_person_number_by_member_number(member_number)
                                    if person_number:
                                        person_details = dna_client.get_taxid_data_by_person_number(person_number)
                                        if person_details:
                                            dna_cache[member_number] = person_details
                                            logging.info(f"[Dashboard Background] Successfully pre-fetched DNA data for member {member_number} (fallback)")
                            
                            # Pre-fetch transactions for each account
                            if person_details and 'accounts' in person_details:
                                logging.info(f"[Dashboard Background] Pre-fetching transactions for all accounts of member {member_number}")
                                
                                if member_number not in transaction_cache:
                                    transaction_cache[member_number] = {}
                                    
                                for account in person_details['accounts']:
                                    account_number = account.get('account_number')
                                    if account_number:
                                        if account_number not in transaction_cache[member_number]:
                                            logging.info(f"[Dashboard Background] Fetching transactions for account {account_number}")
                                            try:
                                                transactions = dna_client.get_financial_transactions(account_number, limit=50)  # Get more for background cache
                                                if transactions is not None:
                                                    transaction_cache[member_number][account_number] = transactions
                                                    logging.info(f"[Dashboard Background] Successfully pre-fetched {len(transactions)} transactions for account {account_number}")
                                                else:
                                                    logging.warning(f"[Dashboard Background] Failed to fetch transactions for account {account_number}")
                                                    transaction_cache[member_number][account_number] = []
                                            except Exception as tx_e:
                                                logging.error(f"[Dashboard Background] Error fetching transactions for account {account_number}: {tx_e}", exc_info=True)
                                                transaction_cache[member_number][account_number] = []
                                        else:
                                            logging.info(f"[Dashboard Background] Using cached transactions for account {account_number}")
                                
                                logging.info(f"[Dashboard Background] Completed pre-fetching transactions for member {member_number}")
                            
                        except Exception as e:
                            logging.warning(f"[Dashboard Background] Failed to pre-fetch data for member {member_number}: {e}")
                
                logging.info(f"[Dashboard Background] Completed DNA and transaction pre-fetch for all members. DNA cache size: {len(dna_cache)}, Transaction cache size: {len(transaction_cache)}")
            
            background_thread = threading.Thread(target=prefetch_all_data_background)
            background_thread.daemon = True
            background_thread.start()
            logging.info("[Dashboard] Started background thread for DNA and transaction pre-fetching")

    except Exception as e:
        logging.error(f"[Dashboard] Exception fetching dashboard data: {e}", exc_info=True)
        waiting_list = []
        handled_list = []
        waiting_count = 0

    # Transform data for new UI format
    visitors = []
    
    # Add waiting members as active visitors
    for member in waiting_list:
        visitor = {
            'id': member.get('FacingMemberID'),
            'name': member.get('Name', 'Unknown'),
            'checkin_time': member.get('CreatedDate').strftime('%I:%M %p') if member.get('CreatedDate') else 'Unknown',
            'status': 'waiting'
        }
        visitors.append(visitor)
    
    # Add handled members as completed visitors - use UpdatedDate for completion time
    for member in handled_list:
        # Use UpdatedDate for completion time if available, otherwise fall back to CreatedDate
        completion_time = 'Unknown'
        if member.get('UpdatedDate'):
            completion_time = member.get('UpdatedDate').strftime('%I:%M %p')
        elif member.get('CreatedDate'):
            completion_time = member.get('CreatedDate').strftime('%I:%M %p')
        
        visitor = {
            'id': member.get('FacingMemberID'),
            'name': member.get('Name', 'Unknown'),
            'checkin_time': completion_time,
            'status': 'done'
        }
        visitors.append(visitor)

    return render_template(
        'dashboard.html',
        visitors=visitors,
        waiting_count=waiting_count
    )

@app.route('/kiosk-queue')
def view_kiosk_queue():
    """Displays the kiosk check-in queue with Waiting and Handled tabs."""
    waiting_list = []
    handled_list = []
    waiting_count = 0
    db_error_waiting = None
    db_error_handled = None

    try:
        # Fetch waiting kiosk check-ins
        waiting_list_result, error_waiting = database.get_kiosk_queue(status='Waiting')
        if error_waiting:
            logging.error(f"[Kiosk Queue] Error fetching waiting check-ins: {error_waiting}")
            db_error_waiting = "Could not load waiting list."
        elif waiting_list_result:
            waiting_list = waiting_list_result

        # Fetch handled kiosk check-ins
        handled_list_result, error_handled = database.get_kiosk_queue(status='Handled')
        if error_handled:
            logging.error(f"[Kiosk Queue] Error fetching handled check-ins: {error_handled}")
            db_error_handled = "Could not load handled list."
        elif handled_list_result:
            handled_list = handled_list_result

        # Fetch waiting count
        count, error_count = database.get_kiosk_queue_count(status='Waiting')
        if error_count:
            logging.error(f"[Kiosk Queue] Error fetching waiting count: {error_count}")
            waiting_count = len(waiting_list)
            if not db_error_waiting and not db_error_handled:
                flash("Could not load waiting count.", 'warning')
        else:
            waiting_count = count

        # Start background pre-fetching for waiting members
        if waiting_list and dna_client:
            def prefetch_all_data_background():
                """Pre-fetch DNA data and transactions for members in a background thread."""
                global dna_cache, transaction_cache
                logging.info(f"[Background] Starting DNA and transaction pre-fetch for {len(waiting_list)} members")
                for member in waiting_list:
                    member_number = member.get('MemberNumber')
                    if member_number:
                        try:
                            logging.info(f"[Background] Pre-fetching DNA data for member {member_number}")
                            person_details = None
                            
                            if member_number in dna_cache:
                                person_details = dna_cache[member_number]
                                logging.info(f"[Background] Using cached DNA data for member {member_number}")
                            else:
                                try:
                                    person_details = dna_client.get_person_detail_by_member_number(member_number)
                                    if person_details:
                                        dna_cache[member_number] = person_details
                                        logging.info(f"[Background] Successfully pre-fetched DNA data for member {member_number}")
                                except AttributeError:
                                    person_number = dna_client.get_person_number_by_member_number(member_number)
                                    if person_number:
                                        person_details = dna_client.get_taxid_data_by_person_number(person_number)
                                        if person_details:
                                            dna_cache[member_number] = person_details
                                            logging.info(f"[Background] Successfully pre-fetched DNA data for member {member_number} (fallback)")
                            
                            # Pre-fetch transactions for each account
                            if person_details and 'accounts' in person_details:
                                logging.info(f"[Background] Pre-fetching transactions for all accounts of member {member_number}")
                                
                                if member_number not in transaction_cache:
                                    transaction_cache[member_number] = {}
                                    
                                for account in person_details['accounts']:
                                    account_number = account.get('account_number')
                                    if account_number:
                                        if account_number not in transaction_cache[member_number]:
                                            logging.info(f"[Background] Fetching transactions for account {account_number}")
                                            try:
                                                transactions = dna_client.get_financial_transactions(account_number, limit=10)
                                                if transactions is not None:
                                                    transaction_cache[member_number][account_number] = transactions
                                                    logging.info(f"[Background] Successfully pre-fetched {len(transactions)} transactions for account {account_number}")
                                                else:
                                                    logging.warning(f"[Background] Failed to fetch transactions for account {account_number}")
                                                    transaction_cache[member_number][account_number] = []
                                            except Exception as tx_e:
                                                logging.error(f"[Background] Error fetching transactions for account {account_number}: {tx_e}", exc_info=True)
                                                transaction_cache[member_number][account_number] = []
                                        else:
                                            logging.info(f"[Background] Using cached transactions for account {account_number}")
                                
                                logging.info(f"[Background] Completed pre-fetching transactions for member {member_number}")
                            
                        except Exception as e:
                            logging.warning(f"[Background] Failed to pre-fetch data for member {member_number}: {e}")
                
                logging.info(f"[Background] Completed DNA and transaction pre-fetch for all members. DNA cache size: {len(dna_cache)}, Transaction cache size: {len(transaction_cache)}")
            
            background_thread = threading.Thread(target=prefetch_all_data_background)
            background_thread.daemon = True
            background_thread.start()
            logging.info("[Kiosk Queue] Started background thread for DNA and transaction pre-fetching")

    except Exception as e:
        logging.error(f"[Kiosk Queue] Exception fetching kiosk queue data: {e}", exc_info=True)
        flash("An unexpected error occurred loading kiosk queue data.", 'danger')
        waiting_list = []
        handled_list = []
        waiting_count = 0

    if db_error_waiting:
        flash(db_error_waiting, 'danger')
    if db_error_handled:
        flash(db_error_handled, 'danger')

    return render_template(
        'kiosk_queue.html',
        waiting_list=waiting_list,
        handled_list=handled_list,
        waiting_count=waiting_count
    )

@app.route('/handle-kiosk-entry/<int:entry_id>', methods=['POST'])
def handle_kiosk_entry(entry_id):
    """Handles marking a kiosk queue entry as 'Handled'."""
    logging.info(f"[Kiosk Queue] Attempting to mark entry ID {entry_id} as Handled.")
    success, message = database.update_kiosk_queue_status(entry_id, 'Handled')

    if success:
        flash(f"Entry #{entry_id} marked as handled.", 'success')
    else:
        log_message = f"Failed to mark entry ID {entry_id} as handled."
        if message:
            log_message += f" Reason: {message}"
            if "schema error" in message.lower():
                flash("Cannot update status due to a database configuration issue (Missing 'Status' column?). Please contact administrator.", 'danger')
            elif "not found" in message.lower() or "already has status" in message.lower():
                flash(f"Could not update entry #{entry_id}: {message}", 'warning')
            else:
                flash(f"An error occurred updating entry #{entry_id}.", 'danger')
        else:
            flash(f"An unexpected error occurred updating entry #{entry_id}.", 'danger')
        logging.warning(log_message)

    return redirect(url_for('dashboard'))

@app.route('/pickup/<int:visitor_id>')
def pickup(visitor_id):
    """Handle member pickup - marks them as handled and redirects to dashboard."""
    logging.info(f"[Dashboard] Attempting to mark member ID {visitor_id} as handled via pickup.")
    success, message = database.update_kiosk_queue_status(visitor_id, 'Handled')
    
    if success:
        logging.info(f"[Dashboard] Member ID {visitor_id} successfully marked as handled.")
    else:
        logging.warning(f"[Dashboard] Failed to mark member ID {visitor_id} as handled: {message}")
    
    return redirect(url_for('dashboard'))

@app.route('/api/member/<int:member_id>')
def get_member_data(member_id):
    """API endpoint to get member data for the dashboard modal."""
    try:
        # Get member record
        record, error = database.get_facing_member_details(member_id)
        if error or not record:
            return jsonify({'error': 'Member not found'}), 404
        
        member_number = record.get('MemberNumber')
        if not member_number:
            return jsonify({'error': 'No member number associated with this check-in'}), 400
        
        # Get DNA data
        dna_data = None
        ml_data = None
        accounts = []
        transactions = {}
        insights = []
        
        if member_number in dna_cache:
            dna_data = dna_cache[member_number]
        elif dna_client:
            try:
                dna_data = dna_client.get_person_detail_by_member_number(member_number)
                if dna_data:
                    dna_cache[member_number] = dna_data
            except Exception as e:
                logging.error(f"[API] Error fetching DNA data for member {member_number}: {e}")
        
        # Get MeridianLink data
        if dna_data and dna_data.get('ssn') and ml_client:
            try:
                ml_data = ml_client.query_meridian_link(dna_data['ssn'])
            except Exception as e:
                logging.error(f"[API] Error fetching MeridianLink data: {e}")
        
        # Build accounts list (DNA accounts + loans)
        if dna_data and dna_data.get('accounts'):
            for account in dna_data['accounts']:
                account_type = account.get('account_type', 'Account')
                account_number = account.get('account_number', '')
                balance = account.get('balance', '0.00')
                accounts.append(f"{account_type} - ${balance}")
        
        # Add loans to accounts list
        if ml_data:
            for loan in ml_data:
                loan_type = loan.get('loan_type', 'Loan')
                loan_num = loan.get('loan_num', '')
                accounts.append(f"{loan_type} #{loan_num}")
        
        # Get transactions for first account
        if member_number in transaction_cache and transaction_cache[member_number]:
            first_account = list(transaction_cache[member_number].keys())[0]
            transactions[accounts[0] if accounts else 'Account'] = transaction_cache[member_number][first_account][:8]
        
        # Get cached insights
        if member_id in insight_cache:
            insights_text = insight_cache[member_id]
            insights = insights_text.split('\n') if insights_text else []
        
        return jsonify({
            'accounts': accounts,
            'transactions': transactions,
            'insights': insights[:4],  # Limit to 4 for UI
            'member_info': {
                'name': dna_data.get('firstname', '') + ' ' + dna_data.get('lastname', '') if dna_data else record.get('Name', ''),
                'member_number': member_number
            }
        })
        
    except Exception as e:
        logging.error(f"[API] Error in get_member_data for member {member_id}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/member_details/<int:checkin_id>')
def member_details(checkin_id):
    """Display detailed member information for a check-in."""
    global dna_cache, transaction_cache
    try:
        # Fetch check-in record from DB
        record, error = database.get_facing_member_details(checkin_id)
        if error or not record:
            flash("Check-in record not found.", "error")
            return redirect(url_for('view_kiosk_queue'))

        member_number = record.get('MemberNumber')
        
        # Initialize data and connection flags
        dna_data = None
        ml_data = None
        dna_connected = False
        ml_connected = False
        
        # Check if we have cached DNA data for this member
        if member_number and member_number in dna_cache:
            logging.info(f"[Member Details] Using cached DNA data for member {member_number}")
            dna_data = dna_cache[member_number]
            dna_connected = True
        elif not member_number:
            flash("No member number associated with this check-in.", "warning")
            logging.warning(f"No member number for check-in ID {checkin_id}")
        elif not dna_client:
            flash("DNA API client not available. Member details may be incomplete.", "warning")
            logging.warning("DNA API client not available for member details lookup")
        else:
            # Fetch DNA Data Synchronously
            logging.info(f"[Member Details] Attempting synchronous DNA fetch for member {member_number}")
            try:
                person_details = dna_client.get_person_detail_by_member_number(member_number)
                if person_details:
                    dna_data = person_details
                    dna_cache[member_number] = dna_data
                    dna_connected = True
                    logging.info(f"[Member Details] Successfully fetched DNA data for member {member_number}")
                else:
                    logging.warning(f"[Member Details] get_person_detail_by_member_number returned None for member {member_number}")
                    dna_connected = False
                    flash("Could not retrieve primary details from DNA.", "warning")

            except AttributeError:
                logging.warning("[Member Details] get_person_detail_by_member_number not found, attempting fallback.")
                try:
                    person_number = dna_client.get_person_number_by_member_number(member_number)
                    if person_number:
                        fallback_data = dna_client.get_taxid_data_by_person_number(person_number)
                        if fallback_data:
                            dna_data = fallback_data
                            dna_cache[member_number] = dna_data
                            dna_connected = True
                            logging.info(f"[Member Details] Successfully fetched DNA data for member {member_number} (fallback)")
                        else:
                            logging.warning(f"[Member Details] DNA API connection failed (fallback) for member {member_number}")
                            dna_connected = False
                            flash("Could not retrieve fallback details from DNA.", "warning")
                    else:
                        logging.warning(f"[Member Details] Person number not found for member {member_number} (fallback)")
                        dna_connected = False
                        flash("Member number not found in DNA (fallback).", "warning")
                except Exception as fallback_e:
                    logging.error(f"[Member Details] DNA API call failed (fallback) for member {member_number}: {fallback_e}", exc_info=True)
                    dna_connected = False
                    flash("Error during fallback DNA lookup.", "danger")
            except Exception as e:
                logging.error(f"[Member Details] DNA API call failed for member {member_number}: {e}", exc_info=True)
                dna_connected = False
                flash("An error occurred fetching data from DNA.", "danger")

        # Fetch MeridianLink Data
        if dna_connected and dna_data and dna_data.get('ssn') and ml_client:
            ssn = dna_data['ssn']
            logging.info(f"[Member Details] Attempting MeridianLink lookup for SSN ending in: {ssn[-4:]}")
            try:
                ml_data = ml_client.query_meridian_link(ssn)
                if ml_data is not None:
                    ml_connected = True
                    logging.info(f"[Member Details] MeridianLink lookup successful. Found {len(ml_data)} loan(s).")
                else:
                    ml_connected = False
                    logging.warning(f"[Member Details] MeridianLink lookup failed (returned None) for SSN ending in: {ssn[-4:]}")
                    flash("Could not retrieve loan data from MeridianLink.", "warning")
            except Exception as ml_e:
                logging.error(f"[Member Details] Error during MeridianLink lookup: {ml_e}", exc_info=True)
                ml_connected = False
                flash("An error occurred during MeridianLink lookup.", "danger")
        elif dna_connected and dna_data and not dna_data.get('ssn'):
            logging.warning(f"[Member Details] SSN not found in DNA data for member {member_number}. Skipping MeridianLink lookup.")
        elif not ml_client:
            logging.warning("[Member Details] MeridianLink client not available. Skipping ML lookup.")

        # Get transactions from cache or fetch if needed
        account_transactions = {}
        if dna_connected and dna_data and dna_data.get('accounts'):
            logging.info(f"[Member Details] Getting transactions for all accounts")
            
            if member_number in transaction_cache:
                logging.info(f"[Member Details] Using cached transactions for member {member_number}")
                account_transactions = transaction_cache[member_number]
            else:
                transaction_cache[member_number] = {}
                
                if dna_client:
                    for account in dna_data['accounts']:
                        account_number = account.get('account_number')
                        if account_number:
                            logging.info(f"[Member Details] Fetching transactions for account {account_number}")
                            try:
                                transactions = dna_client.get_financial_transactions(account_number, limit=10)
                                if transactions is not None:
                                    transaction_cache[member_number][account_number] = transactions
                                    logging.info(f"[Member Details] Successfully fetched {len(transactions)} transactions for account {account_number}")
                                else:
                                    logging.warning(f"[Member Details] Failed to fetch transactions for account {account_number}")
                                    transaction_cache[member_number][account_number] = []
                            except Exception as tx_e:
                                logging.error(f"[Member Details] Error fetching transactions for account {account_number}: {tx_e}", exc_info=True)
                                transaction_cache[member_number][account_number] = []
                    
                    account_transactions = transaction_cache[member_number]
                else:
                    logging.warning("[Member Details] DNA client not available for transaction fetching")
            
            logging.info(f"[Member Details] Using transactions for {len(account_transactions)} accounts")

        return render_template('member_details.html',
                               record=record,
                               dna_data=dna_data,
                               ml_data=ml_data,
                               dna_connected=dna_connected,
                               ml_connected=ml_connected,
                               checkin_id=checkin_id,
                               account_transactions=account_transactions)

    except Exception as e:
        logging.error(f"Unexpected error in member_details route: {e}", exc_info=True)
        flash("An unexpected error occurred while loading member details.", "error")
        return redirect(url_for('view_kiosk_queue'))

@app.route('/get_transactions/<account_number>')
def get_transactions(account_number):
    """Fetches transaction history for a specific account number."""
    if not dna_client:
        logging.warning(f"[AJAX Transactions] DNA client not available for account {account_number}")
        return jsonify({'error': 'DNA client not available'}), 503

    try:
        transactions = dna_client.get_financial_transactions(account_number, limit=10)

        if transactions is None:
            logging.warning(f"[AJAX Transactions] get_financial_transactions returned None for account {account_number}")
            return jsonify({'error': 'Failed to retrieve transactions'}), 500
        else:
            logging.info(f"[AJAX Transactions] Successfully retrieved {len(transactions)} transactions for account {account_number}")
            return jsonify(transactions)

    except Exception as e:
        logging.error(f"[AJAX Transactions] Unexpected error fetching transactions for account {account_number}: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500

# ─── AI INSIGHTS GENERATION ────────────────────────────────────────────────────
def _generate_insights_thread(checkin_id):
    """Background worker to call your HTTP‐based generator and cache the results."""
    try:
        from insight_generator import generate_insights

        record, _ = database.get_facing_member_details(checkin_id)
        mnum = record.get('MemberNumber')

        txs_by_account = transaction_cache.get(mnum, {})
        all_transactions = []
        for acct, items in txs_by_account.items():
            if isinstance(items, list):
                # Filter to only last 30 days for insights
                recent_transactions = filter_recent_transactions(items, INSIGHTS_TRANSACTION_DAYS)
                all_transactions.extend(recent_transactions)

        logging.info(f"[INSIGHTS] Generating insights for check-in {checkin_id} using {len(all_transactions)} transactions from last {INSIGHTS_TRANSACTION_DAYS} days (filtered from {sum(len(items) if isinstance(items, list) else 0 for items in txs_by_account.values())} total)…")
        insights_list = generate_insights(all_transactions)

        insight_cache[checkin_id] = "\n".join(insights_list)
        logging.info(f"[INSIGHTS] Cached {len(insights_list)} insights for check-in {checkin_id}")

    except Exception as e:
        logging.error(f"[INSIGHTS] Insight generation failed for check-in {checkin_id}: {e}", exc_info=True)
        insight_cache[checkin_id] = "Error generating insights."

@app.route('/generate_insights/<int:checkin_id>', methods=['POST'])
def generate_insights_route(checkin_id):
    """Kick off background insight generation once."""
    logging.info(f"[INSIGHTS] Request to generate insights for check-in {checkin_id}")
    if checkin_id not in insight_cache:
        threading.Thread(
            target=_generate_insights_thread,
            args=(checkin_id,),
            daemon=True
        ).start()
    return jsonify({'status': 'started'})

@app.route('/get_insights/<int:checkin_id>')
def get_insights_route(checkin_id):
    """Poll for cached insights or pending."""
    if checkin_id in insight_cache:
        return jsonify({'status': 'done', 'insights': insight_cache[checkin_id]})
    else:
        return jsonify({'status': 'pending'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('WAITING_PORT', 8082)), debug=app.config['DEBUG'])
