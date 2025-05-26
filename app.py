# waiting/app.py - Kiosk Queue Management Application
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import logging
from logging.handlers import RotatingFileHandler
import html 
from dotenv import load_dotenv
from datetime import datetime, timedelta, date # Added date
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

# --- Prefetch Locking ---
prefetch_locks = set()
recent_prefetches = TTLCache(maxsize=200, ttl=60) # Track recent prefetches for 60 seconds

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
                tx_date = datetime.strptime(tx_date_str, '%Y-%m-%d')
                if tx_date >= cutoff_date:
                    recent_transactions.append(tx)
            except ValueError:
                recent_transactions.append(tx)
        else:
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
    return {'now': datetime.now(datetime.UTC) if hasattr(datetime, 'UTC') else datetime.utcnow()}

@app.context_processor
def inject_visitor_count():
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
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard(selected_member_data=None, dna_error_message=None, ml_error_message=None, 
              snapshot_accounts=None, snapshot_transactions=None, snapshot_insights=None):
    waiting_list = []
    handled_list = []
    waiting_count = 0
    db_error_waiting = None
    db_error_handled = None

    try:
        waiting_list_result, error_waiting = database.get_kiosk_queue(status='Waiting')
        if error_waiting:
            logging.error(f"[Dashboard] Error fetching waiting check-ins: {error_waiting}")
            db_error_waiting = "Could not load waiting list."
        elif waiting_list_result:
            waiting_list = waiting_list_result

        # Fetch handled kiosk check-ins for today
        handled_list_result, error_handled = database.get_kiosk_queue(status='Handled', filter_by_date=date.today())
        if error_handled:
            logging.error(f"[Dashboard] Error fetching handled check-ins for today: {error_handled}")
            db_error_handled = "Could not load handled list."
        elif handled_list_result:
            handled_list = handled_list_result

        count, error_count = database.get_kiosk_queue_count(status='Waiting')
        if error_count:
            logging.error(f"[Dashboard] Error fetching waiting count: {error_count}")
            waiting_count = len(waiting_list)
        else:
            waiting_count = count

        if waiting_list and dna_client:
            def prefetch_all_data_background():
                global dna_cache, transaction_cache, prefetch_locks, recent_prefetches
                logging.info(f"[Dashboard Background] Starting DNA and transaction pre-fetch for {len(waiting_list)} members")
                for member_checkin_info in waiting_list: 
                    member_number_from_db = member_checkin_info.get('MemberNumber') 
                    
                    if not member_number_from_db: 
                        logging.info(f"[Dashboard Background] Skipping pre-fetch for check-in ID {member_checkin_info.get('FacingMemberID')} as no member number is set.")
                        continue

                    if member_number_from_db in prefetch_locks:
                        logging.info(f"[Dashboard Background] Pre-fetch for member {member_number_from_db} (check-in {member_checkin_info.get('FacingMemberID')}) already in progress. Skipping.")
                        continue
                    if member_number_from_db in recent_prefetches:
                        logging.info(f"[Dashboard Background] Pre-fetch for member {member_number_from_db} (check-in {member_checkin_info.get('FacingMemberID')}) completed recently. Skipping.")
                        continue
                        
                    try:
                        prefetch_locks.add(member_number_from_db)
                        logging.info(f"[Dashboard Background] Pre-fetching DNA data for member {member_number_from_db} (check-in {member_checkin_info.get('FacingMemberID')})")
                        person_details = None
                        if member_number_from_db in dna_cache:
                            person_details = dna_cache[member_number_from_db]
                            logging.info(f"[Dashboard Background] Using cached DNA data for member {member_number_from_db}")
                        else:
                            try:
                                person_details = dna_client.get_person_detail_by_member_number(member_number_from_db)
                                if person_details:
                                    dna_cache[member_number_from_db] = person_details
                                    logging.info(f"[Dashboard Background] Successfully pre-fetched DNA data for member {member_number_from_db}")
                            except AttributeError: 
                                person_number_from_dna_lookup = dna_client.get_person_number_by_member_number(member_number_from_db)
                                if person_number_from_dna_lookup:
                                    person_details = dna_client.get_taxid_data_by_person_number(person_number_from_dna_lookup)
                                    if person_details:
                                        dna_cache[member_number_from_db] = person_details
                                        logging.info(f"[Dashboard Background] Successfully pre-fetched DNA data for member {member_number_from_db} (fallback)")
                        
                        if person_details and 'accounts' in person_details:
                            logging.info(f"[Dashboard Background] Pre-fetching transactions for all accounts of member {member_number_from_db}")
                            if member_number_from_db not in transaction_cache:
                                transaction_cache[member_number_from_db] = {}
                            for account in person_details['accounts']:
                                account_number = account.get('account_number')
                                if account_number and account_number not in transaction_cache[member_number_from_db]:
                                    logging.info(f"[Dashboard Background] Fetching transactions for account {account_number}")
                                    try:
                                        transactions = dna_client.get_financial_transactions(account_number, limit=50)
                                        if transactions is not None:
                                            transaction_cache[member_number_from_db][account_number] = transactions
                                        else:
                                            transaction_cache[member_number_from_db][account_number] = []
                                    except Exception as tx_e:
                                        logging.error(f"[Dashboard Background] Error fetching transactions for account {account_number}: {tx_e}", exc_info=True)
                                        transaction_cache[member_number_from_db][account_number] = []
                                elif account_number in transaction_cache[member_number_from_db]:
                                     logging.info(f"[Dashboard Background] Using cached transactions for account {account_number}")
                            logging.info(f"[Dashboard Background] Completed pre-fetching transactions for member {member_number_from_db}")
                    except Exception as e:
                        logging.warning(f"[Dashboard Background] Failed to pre-fetch data for member {member_number_from_db}: {e}")
                    finally:
                        if member_number_from_db in prefetch_locks:
                            prefetch_locks.remove(member_number_from_db)
                        recent_prefetches[member_number_from_db] = True
                logging.info(f"[Dashboard Background] Completed DNA and transaction pre-fetch. DNA cache: {len(dna_cache)}, Tx cache: {len(transaction_cache)}")
            
            background_thread = threading.Thread(target=prefetch_all_data_background)
            background_thread.daemon = True
            background_thread.start()
            logging.info("[Dashboard] Started background thread for DNA and transaction pre-fetching")

    except Exception as e:
        logging.error(f"[Dashboard] Exception fetching dashboard data: {e}", exc_info=True)
        waiting_list, handled_list, waiting_count = [], [], 0

    # Transform data for new UI format (this is for the main lists, not the snapshot)
    visitors_transformed = []
    for member in waiting_list:
        visitors_transformed.append({
            'id': member.get('FacingMemberID'), 'name': member.get('Name', 'Unknown'),
            'checkin_time': member.get('CreatedDate').strftime('%I:%M %p') if member.get('CreatedDate') else 'Unknown',
            'status': 'waiting'
        })
    for member in handled_list:
        completion_time = (member.get('UpdatedDate') or member.get('CreatedDate')).strftime('%I:%M %p') if (member.get('UpdatedDate') or member.get('CreatedDate')) else 'Unknown'
        visitors_transformed.append({
            'id': member.get('FacingMemberID'), 'name': member.get('Name', 'Unknown'),
            'checkin_time': completion_time, 'status': 'done'
        })
        
    return render_template('dashboard.html', 
                           visitors=visitors_transformed, 
                           waiting_count=waiting_count,
                           selected=selected_member_data, # This is for the snapshot card
                           accounts=snapshot_accounts, # For snapshot
                           transactions=snapshot_transactions, # For snapshot
                           ai_insights=snapshot_insights, # For snapshot
                           dna_error_message=dna_error_message, # For snapshot
                           ml_error_message=ml_error_message) # For snapshot

@app.route('/kiosk-queue') 
def view_kiosk_queue():
    waiting_list = []
    try:
        waiting_list_result, _ = database.get_kiosk_queue(status='Waiting')
        if waiting_list_result: waiting_list = waiting_list_result
    except Exception as e:
        logging.error(f"[Kiosk Queue] Exception: {e}", exc_info=True)
    return render_template('kiosk_queue.html', waiting_list=waiting_list, handled_list=[], waiting_count=len(waiting_list))


@app.route('/handle-kiosk-entry/<int:entry_id>', methods=['POST'])
def handle_kiosk_entry(entry_id):
    logging.info(f"[Kiosk Queue] Attempting to mark entry ID {entry_id} as Handled.")
    success, message = database.update_kiosk_queue_status(entry_id, 'Handled')
    if success: flash(f"Entry #{entry_id} marked as handled.", 'success')
    else: flash(f"Error updating entry #{entry_id}: {message}", 'danger')
    return redirect(url_for('dashboard'))

@app.route('/pickup/<int:visitor_id>')
def pickup(visitor_id):
    logging.info(f"[Dashboard] Attempting to mark member ID {visitor_id} as handled via pickup.")
    success, db_message = database.update_kiosk_queue_status(visitor_id, 'Handled') 
    
    if not success:
        logging.warning(f"[Dashboard] Failed to mark member ID {visitor_id} as handled: {db_message}")
        flash(f"Error marking member as handled: {db_message}", "danger")
        return redirect(url_for('dashboard')) # Redirect to plain dashboard on error

    logging.info(f"[Dashboard] Member ID {visitor_id} successfully marked as handled. Now fetching details for snapshot.")

    # Fetch data for the snapshot
    record, error = database.get_facing_member_details(visitor_id)
    if error or not record:
        flash(f"Could not retrieve details for picked-up member (ID: {visitor_id}). Displaying dashboard.", "warning")
        return redirect(url_for('dashboard'))

    member_number_to_use = record.get('MemberNumber')
    dna_data, ml_data, account_transactions_for_snapshot = None, None, {}
    dna_connected, ml_connected = False, False
    dna_error_message, ml_error_message = None, None
    snapshot_accounts_list = []
    snapshot_insights_list = []

    if not DNA_CLIENT_AVAILABLE:
        dna_error_message = "DNA Client is not available."
    elif not member_number_to_use:
        dna_error_message = "No member number available for this check-in to query DNA."
    else:
        if member_number_to_use in dna_cache:
            dna_data = dna_cache[member_number_to_use]
            dna_connected = True
        else:
            try:
                dna_data = dna_client.get_person_detail_by_member_number(member_number_to_use)
                if dna_data and dna_data.get('persnbr'):
                    dna_cache[member_number_to_use] = dna_data
                    dna_connected = True
                elif dna_data: # Incomplete data
                    dna_connected = True
                    dna_error_message = f"Core DNA data is incomplete for member {member_number_to_use}."
                else: # No data found
                    dna_connected = True 
                    dna_error_message = f"Member data not found in DNA for {member_number_to_use}."
            except Exception as e:
                dna_error_message = f"Error fetching DNA data for {member_number_to_use}: {str(e)}"
                logging.error(f"[Pickup] DNA fetch error for {member_number_to_use}: {e}", exc_info=True)
    
    if dna_data and dna_data.get('ssn'):
        if not ML_CLIENT_AVAILABLE:
            ml_error_message = "MeridianLink Client is not available."
        else:
            try:
                ml_data_result = ml_client.query_meridian_link(dna_data['ssn'])
                if ml_data_result is not None:
                    ml_data = ml_data_result
                    ml_connected = True
                    if not ml_data:
                         ml_error_message = f"No loan applications found in MeridianLink for member {member_number_to_use}."
                else: # None means error or "not found" from client
                    ml_connected = True 
                    ml_error_message = f"Could not retrieve loan data from MeridianLink for member {member_number_to_use}."
            except Exception as e:
                ml_error_message = f"Error fetching MeridianLink data for {member_number_to_use}: {str(e)}"
                logging.error(f"[Pickup] ML fetch error for {member_number_to_use}: {e}", exc_info=True)
    elif dna_data and not dna_error_message: # dna_data exists but no ssn
        ml_error_message = "SSN not found in DNA data; cannot query MeridianLink."


    if dna_data and dna_data.get('accounts') and member_number_to_use:
        if member_number_to_use in transaction_cache:
            account_transactions_for_snapshot = transaction_cache[member_number_to_use]
        elif dna_client:
            transaction_cache[member_number_to_use] = {}
            for account in dna_data['accounts']:
                acc_num = account.get('account_number')
                if acc_num:
                    try:
                        txns = dna_client.get_financial_transactions(acc_num, limit=10) # Limit for snapshot
                        transaction_cache[member_number_to_use][acc_num] = txns if txns is not None else []
                    except Exception as e:
                        logging.error(f"[Pickup] Transaction fetch error for account {acc_num} of member {member_number_to_use}: {e}", exc_info=True)
                        transaction_cache[member_number_to_use][acc_num] = []
            account_transactions_for_snapshot = transaction_cache[member_number_to_use]

    # Prepare accounts list for snapshot template (similar to API)
    if dna_data and dna_data.get('accounts'):
        for acc in dna_data['accounts']:
            snapshot_accounts_list.append(f"{acc.get('account_type', 'Account')} - ${acc.get('balance', '0.00')}")
    if ml_data: # ml_data is a list of loans
        for loan in ml_data:
            snapshot_accounts_list.append(f"{loan.get('loan_type', 'Loan')} #{loan.get('loan_num', '')}")
            
    # Prepare transactions for snapshot (first account, limited)
    snapshot_txns_for_template = {}
    if account_transactions_for_snapshot and snapshot_accounts_list:
        first_account_key = list(account_transactions_for_snapshot.keys())[0] if account_transactions_for_snapshot else None
        if first_account_key:
            # The key for snapshot_txns_for_template should be the account description used in the dropdown
            # For simplicity, using the first account from the combined list.
            snapshot_txns_for_template[snapshot_accounts_list[0]] = account_transactions_for_snapshot[first_account_key][:8]


    if visitor_id in insight_cache:
        snapshot_insights_list = insight_cache[visitor_id].split('\n') if insight_cache[visitor_id] else []
    elif member_number_to_use: # Only generate if there's a member number
        threading.Thread(target=_generate_insights_thread, args=(visitor_id,), daemon=True).start()
        snapshot_insights_list = ["AI analysis in progress..."]


    selected_data_for_template = {
        'id': visitor_id,
        'name': (dna_data.get('firstname', '') + ' ' + dna_data.get('lastname', '')).strip() if dna_data and dna_data.get('firstname') else record.get('Name', 'N/A'),
        'member_number': member_number_to_use or "N/A",
        # Add any other fields the snapshot part of dashboard.html might expect in 'selected'
    }
    
    # Re-fetch dashboard lists for rendering
    waiting_list_result, _ = database.get_kiosk_queue(status='Waiting')
    handled_list_result, _ = database.get_kiosk_queue(status='Handled', filter_by_date=date.today())
    waiting_count_val, _ = database.get_kiosk_queue_count(status='Waiting')

    visitors_transformed = []
    for member in waiting_list_result or []:
        visitors_transformed.append({
            'id': member.get('FacingMemberID'), 'name': member.get('Name', 'Unknown'),
            'checkin_time': member.get('CreatedDate').strftime('%I:%M %p') if member.get('CreatedDate') else 'Unknown',
            'status': 'waiting'
        })
    for member in handled_list_result or []:
        completion_time = (member.get('UpdatedDate') or member.get('CreatedDate')).strftime('%I:%M %p') if (member.get('UpdatedDate') or member.get('CreatedDate')) else 'Unknown'
        visitors_transformed.append({
            'id': member.get('FacingMemberID'), 'name': member.get('Name', 'Unknown'),
            'checkin_time': completion_time, 'status': 'done'
        })

    return render_template('dashboard.html',
                           visitors=visitors_transformed,
                           waiting_count=waiting_count_val,
                           selected=selected_data_for_template,
                           accounts=snapshot_accounts_list, 
                           transactions=snapshot_txns_for_template,
                           ai_insights=snapshot_insights_list[:4], # Limit for display
                           dna_error_message=dna_error_message,
                           ml_error_message=ml_error_message)


@app.route('/api/member/<int:checkin_id_for_api>') 
def get_member_data(checkin_id_for_api):
    try:
        record, error = database.get_facing_member_details(checkin_id_for_api)
        if error or not record: return jsonify({'error': 'Member not found'}), 404
        
        member_number_to_use = record.get('MemberNumber') 
        if not member_number_to_use: 
            return jsonify({'error': 'No member number available for API queries', 'member_info': {'name': record.get('Name', 'N/A'), 'member_number': 'N/A'}, 'accounts': [], 'transactions': {}, 'insights': [], 'error_dna': 'No member number provided.', 'error_ml': None}), 200 # Return 200 so modal can display the error

        dna_data, ml_data, accounts, transactions_for_modal = None, None, [], {}
        error_dna, error_ml = None, None
        
        if not DNA_CLIENT_AVAILABLE:
            error_dna = "DNA client is not available."
        elif member_number_to_use in dna_cache:
            dna_data = dna_cache[member_number_to_use]
            logging.info(f"[API] Using cached DNA data for member {member_number_to_use}")
        elif dna_client: # DNA_CLIENT_AVAILABLE is true here
            try:
                dna_data = dna_client.get_person_detail_by_member_number(member_number_to_use)
                if dna_data and dna_data.get('persnbr'):
                    dna_cache[member_number_to_use] = dna_data
                    logging.info(f"[API] Fetched and cached DNA data for member {member_number_to_use}")
                elif dna_data : # Incomplete data
                    error_dna = f"Core DNA data is incomplete for member {member_number_to_use}."
                    logging.warning(f"[API] Incomplete DNA data for {member_number_to_use}")
                else: # No data found
                    error_dna = f"Member data not found in DNA for {member_number_to_use}."
                    logging.warning(f"[API] No DNA data found for member {member_number_to_use}")
            except DNAApiError as e:
                error_dna = f"DNA API error for member {member_number_to_use}: {str(e)}"
                logging.error(f"[API] DNAApiError for member {member_number_to_use}: {e}", exc_info=True)
            except Exception as e:
                error_dna = f"Unexpected error fetching DNA data for member {member_number_to_use}."
                logging.error(f"[API] Unexpected error fetching DNA data for {member_number_to_use}: {e}", exc_info=True)

        if dna_data and dna_data.get('ssn'):
            if not ML_CLIENT_AVAILABLE:
                error_ml = "MeridianLink client is not available."
            elif ml_client: # ML_CLIENT_AVAILABLE is true
                try:
                    ml_data_result = ml_client.query_meridian_link(dna_data['ssn'])
                    if ml_data_result is not None: # Could be empty list (no loans)
                        ml_data = ml_data_result
                        logging.info(f"[API] MeridianLink data fetched for SSN related to member {member_number_to_use}. Loans: {len(ml_data)}")
                        if not ml_data: # Explicitly no loans found
                            error_ml = f"No loan applications found in MeridianLink for member {member_number_to_use}."
                    else: # None from client usually means an error or specific "not found"
                        error_ml = f"Could not retrieve loan data from MeridianLink for member {member_number_to_use}."
                        logging.warning(f"[API] ML query returned None for SSN of member {member_number_to_use}")
                except MeridianLinkError as e:
                    error_ml = f"MeridianLink API error: {str(e)}"
                    logging.error(f"[API] MeridianLinkError for SSN of member {member_number_to_use}: {e}", exc_info=True)
                except Exception as e:
                    error_ml = f"Unexpected error fetching MeridianLink data for member {member_number_to_use}."
                    logging.error(f"[API] Unexpected error fetching ML data for {member_number_to_use}: {e}", exc_info=True)
        elif dna_data and not error_dna: # We have DNA data but no SSN for ML
             error_ml = "SSN not found in DNA data for MeridianLink query."
        elif not dna_data and not error_dna : # No DNA data to begin with, and no explicit DNA error yet
            if DNA_CLIENT_AVAILABLE and member_number_to_use : # If we should have tried DNA
                 error_ml = "MeridianLink query skipped due to missing DNA data."


        if dna_data and dna_data.get('accounts'):
            for acc in dna_data['accounts']: accounts.append(f"{acc.get('account_type', 'Account')} - ${acc.get('balance', '0.00')}")
        if ml_data:
            for loan in ml_data: accounts.append(f"{loan.get('loan_type', 'Loan')} #{loan.get('loan_num', '')}")
        
        if member_number_to_use in transaction_cache and transaction_cache[member_number_to_use]:
            account_keys = list(transaction_cache[member_number_to_use].keys())
            if account_keys and accounts: 
                 transactions_for_modal[accounts[0]] = transaction_cache[member_number_to_use][account_keys[0]][:8]

        insights = insight_cache.get(checkin_id_for_api, "").split('\n') if insight_cache.get(checkin_id_for_api) else []
        
        return jsonify({
            'accounts': accounts, 'transactions': transactions_for_modal, 'insights': insights[:4],
            'member_info': {
                'name': (dna_data.get('firstname', '') + ' ' + dna_data.get('lastname', '')).strip() if dna_data and dna_data.get('firstname') else record.get('Name', 'N/A'), 
                'member_number': member_number_to_use
            },
            'error_dna': error_dna,
            'error_ml': error_ml
        })
    except Exception as e:
        logging.error(f"[API] Error in get_member_data for check-in {checkin_id_for_api}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/member_details/<int:checkin_id>')
def member_details(checkin_id):
    global dna_cache, transaction_cache
    try:
        record, error = database.get_facing_member_details(checkin_id)
        if error or not record:
            flash("Check-in record not found.", "error")
            return redirect(url_for('view_kiosk_queue'))

        member_number_to_use = record.get('MemberNumber') 

        dna_data, ml_data, account_transactions = None, None, {}
        dna_connected, ml_connected = False, False
        dna_error_message, ml_error_message = None, None
        
        if not DNA_CLIENT_AVAILABLE:
            dna_error_message = "DNA Client is not available or failed to initialize. Please check system configuration."
        elif not member_number_to_use:
            # This case is handled by is_partial_data and flash messages already
            flash("No Member Number is currently set for this check-in. Please enter one to fetch details.", "info")
            logging.info(f"No active member number for API lookups for check-in ID {checkin_id}")
        else: # Attempt DNA fetch only if client is available and member_number_to_use exists
            if member_number_to_use in dna_cache:
                logging.info(f"[Member Details] Using cached DNA data for active member {member_number_to_use}")
                dna_data = dna_cache[member_number_to_use]
                dna_connected = True 
                logging.info(f"[Member Details] Using cached DNA data for active member {member_number_to_use}")
            else: # dna_client is available and member_number_to_use exists, but not in cache
                logging.info(f"[Member Details] Attempting synchronous DNA fetch for active member {member_number_to_use}")
                try:
                    person_details = dna_client.get_person_detail_by_member_number(member_number_to_use)
                    if person_details and person_details.get('persnbr'): # Check for essential data
                        dna_data = person_details
                        dna_cache[member_number_to_use] = dna_data
                        dna_connected = True
                        logging.info(f"[Member Details] Successfully fetched DNA data for active member {member_number_to_use}")
                    elif person_details: # Got some data, but it's incomplete
                        dna_data = person_details # Store what we got
                        dna_connected = True # Connection was made
                        dna_error_message = f"Core DNA data is incomplete for member number {member_number_to_use}."
                        logging.warning(f"[Member Details] Incomplete DNA data for {member_number_to_use}: {person_details}")
                    else: # No person_details returned from client call
                        dna_connected = True # Connection was made, but no data found
                        dna_error_message = f"Member data not found in DNA for member number {member_number_to_use}."
                        logging.warning(f"[Member Details] get_person_detail_by_member_number returned None or empty for active member {member_number_to_use}")
                except DNAApiError as e: # Specific API error from client
                    dna_connected = False # Explicitly set as connection/API call failed
                    dna_error_message = f"DNA API error for member {member_number_to_use}: {str(e)}"
                    logging.error(f"[Member Details] DNA API error for active member {member_number_to_use}: {e}", exc_info=True)
                except Exception as e: # Other unexpected errors during DNA fetch
                    dna_connected = False
                    dna_error_message = f"An unexpected error occurred fetching DNA data for member {member_number_to_use}."
                    logging.error(f"[Member Details] Unexpected DNA API call failed for active member {member_number_to_use}: {e}", exc_info=True)

        # MeridianLink Data Fetching
        if not ML_CLIENT_AVAILABLE:
            ml_error_message = "MeridianLink Client is not available or failed to initialize. Please check system configuration."
        elif not dna_data or not dna_data.get('ssn'):
            # This case is handled by is_partial_data or dna_error_message; ML part will just not show data.
            if member_number_to_use and dna_data and not dna_error_message: # Only log if DNA part was seemingly okay
                 logging.warning(f"[Member Details] SSN not found in DNA data for member {member_number_to_use}. Skipping MeridianLink lookup.")
        else: # ML Client available, and we have dna_data with an SSN
            ssn = dna_data['ssn']
            logging.info(f"[Member Details] Attempting MeridianLink lookup for SSN ending in: {ssn[-4:]} (related to member {member_number_to_use})")
            try:
                ml_data_result = ml_client.query_meridian_link(ssn)
                if ml_data_result is not None: # API call was made, result could be empty list (no loans) or list of loans
                    ml_data = ml_data_result
                    ml_connected = True 
                    logging.info(f"[Member Details] MeridianLink lookup successful for SSN related to member {member_number_to_use}. Found {len(ml_data)} loan(s).")
                    if not ml_data: # Empty list means no loans found
                        ml_error_message = f"No loan applications found in MeridianLink for member {member_number_to_use} (SSN provided)."
                else: # query_meridian_link returned None, implying an error or specific "not found"
                    ml_connected = True # Connection was attempted
                    ml_error_message = f"Could not retrieve loan data from MeridianLink for member {member_number_to_use} (SSN provided)."
                    logging.warning(f"[Member Details] MeridianLink lookup returned None for SSN related to member {member_number_to_use}")
            except MeridianLinkError as e: # Specific API error from client
                ml_connected = False
                ml_error_message = f"MeridianLink API error for member {member_number_to_use}: {str(e)}"
                logging.error(f"[Member Details] MeridianLink API error (member {member_number_to_use}): {e}", exc_info=True)
            except Exception as ml_e: # Other unexpected errors
                ml_connected = False
                ml_error_message = f"An unexpected error occurred during MeridianLink lookup for member {member_number_to_use}."
                logging.error(f"[Member Details] Unexpected error during MeridianLink lookup (member {member_number_to_use}): {ml_e}", exc_info=True)
        
        # Transaction Fetching (remains largely the same, depends on dna_data)
        if dna_data and dna_data.get('accounts') and member_number_to_use:
            logging.info(f"[Member Details] Getting transactions for active member {member_number_to_use}")
            if member_number_to_use in transaction_cache:
                account_transactions = transaction_cache[member_number_to_use]
            elif dna_client:
                transaction_cache[member_number_to_use] = {}
                for account in dna_data['accounts']:
                    account_number_val = account.get('account_number')
                    if account_number_val:
                        try:
                            transactions = dna_client.get_financial_transactions(account_number_val, limit=10)
                            transaction_cache[member_number_to_use][account_number_val] = transactions if transactions is not None else []
                        except Exception as tx_e:
                            logging.error(f"[Member Details] Error fetching transactions for account {account_number_val} (member {member_number_to_use}): {tx_e}", exc_info=True)
                            transaction_cache[member_number_to_use][account_number_val] = []
                account_transactions = transaction_cache[member_number_to_use]
        
        is_partial_data = not member_number_to_use or not dna_data or not dna_data.get('persnbr')

        return render_template('member_details.html',
                               record=record, 
                               dna_data=dna_data,
                               ml_data=ml_data,
                               dna_connected=dna_connected, 
                               ml_connected=ml_connected,
                               dna_error_message=dna_error_message,
                               ml_error_message=ml_error_message,
                               is_partial_data=is_partial_data,
                               checkin_id=checkin_id,
                               member_number_to_use=member_number_to_use, 
                               account_transactions=account_transactions)

    except Exception as e:
        logging.error(f"Unexpected error in member_details route for checkin_id {checkin_id}: {e}", exc_info=True)
        flash("An unexpected error occurred while loading member details.", "error")
        return redirect(url_for('view_kiosk_queue'))

@app.route('/update_member_number/<int:checkin_id>', methods=['POST'])
def update_member_number(checkin_id):
    new_member_number_input = request.form.get('new_member_number', '').strip()
    if not new_member_number_input or not new_member_number_input.isdigit():
        flash("Invalid member number format. Please enter a valid number.", "danger")
        return redirect(url_for('member_details', checkin_id=checkin_id))

    current_record, db_error = database.get_facing_member_details(checkin_id)
    if db_error or not current_record:
        flash(f"Could not find check-in record {checkin_id} to update.", "danger")
        return redirect(url_for('view_kiosk_queue'))

    old_active_member_number = current_record.get('MemberNumber') 

    success, message = database.update_member_number_for_checkin(checkin_id, new_member_number_input, 'manual_entry')

    if success:
        flash(f"Member number updated to {new_member_number_input} for check-in {checkin_id}. Fetching details...", "success")
        logging.info(f"Member number for check-in {checkin_id} updated to {new_member_number_input} (manual_entry). Old active was {old_active_member_number}.")

        if old_active_member_number and old_active_member_number != new_member_number_input:
            logging.info(f"Clearing cache for old active member number: {old_active_member_number}")
            dna_cache.pop(old_active_member_number, None)
            transaction_cache.pop(old_active_member_number, None)
        
        dna_cache.pop(new_member_number_input, None)
        transaction_cache.pop(new_member_number_input, None)
        insight_cache.pop(checkin_id, None)

        if dna_client:
            logging.info(f"[UpdateMemberNumber] Attempting synchronous DNA fetch for new active member number: {new_member_number_input}")
            try:
                new_dna_data = dna_client.get_person_detail_by_member_number(new_member_number_input)
                if new_dna_data:
                    dna_cache[new_member_number_input] = new_dna_data
                    logging.info(f"[UpdateMemberNumber] Successfully fetched and cached DNA data for {new_member_number_input}")
                    if new_dna_data.get('ssn') and ml_client:
                        try: ml_client.query_meridian_link(new_dna_data['ssn'])
                        except Exception as ml_e: logging.error(f"[UpdateMemberNumber] Error querying MeridianLink for {new_member_number_input}: {ml_e}")
                    if new_dna_data.get('accounts'):
                        transaction_cache[new_member_number_input] = {}
                        for account in new_dna_data['accounts']:
                            acc_num = account.get('account_number')
                            if acc_num:
                                try:
                                    txns = dna_client.get_financial_transactions(acc_num, limit=10)
                                    transaction_cache[new_member_number_input][acc_num] = txns if txns is not None else []
                                except Exception as tx_e: logging.error(f"[UpdateMemberNumber] Error fetching tx for acc {acc_num} (member {new_member_number_input}): {tx_e}")
                        logging.info(f"[UpdateMemberNumber] Transactions re-fetched for {new_member_number_input}")
                else: 
                    flash(f"Could not retrieve DNA details for the new member number {new_member_number_input}. It may be invalid.", "warning")
            except Exception as e:
                logging.error(f"[UpdateMemberNumber] Error during sync DNA fetch for {new_member_number_input}: {e}", exc_info=True)
                flash("An error occurred fetching data for the new member number.", "danger")
    else:
        flash(f"Failed to update member number: {message}", "danger")

    return redirect(url_for('member_details', checkin_id=checkin_id))

@app.route('/revert_manual_member_number/<int:checkin_id>', methods=['POST'])
def revert_manual_member_number(checkin_id):
    current_record, db_error = database.get_facing_member_details(checkin_id)
    if db_error or not current_record:
        flash(f"Could not find check-in record {checkin_id} to revert.", "danger")
        return redirect(url_for('view_kiosk_queue'))

    member_number_before_revert = current_record.get('MemberNumber') 

    success, message = database.revert_manual_entry(checkin_id)

    if success:
        flash("Manually entered member number has been cleared. Member details reset.", "success")
        logging.info(f"Member number information for check-in {checkin_id} was cleared/reverted.")

        if member_number_before_revert:
            logging.info(f"Clearing cache for prior manual member number: {member_number_before_revert}")
            dna_cache.pop(member_number_before_revert, None)
            transaction_cache.pop(member_number_before_revert, None)
        
        insight_cache.pop(checkin_id, None)
        logging.info(f"Insights cache cleared for check-in {checkin_id} after revert.")

    else:
        flash(f"Failed to clear manual member number: {message}", "danger")
        logging.error(f"Failed to revert manual entry for check-in {checkin_id}: {message}")

    return redirect(url_for('member_details', checkin_id=checkin_id))


@app.route('/get_transactions/<account_number>')
def get_transactions(account_number):
    if not dna_client: return jsonify({'error': 'DNA client not available'}), 503
    try:
        transactions = dna_client.get_financial_transactions(account_number, limit=10)
        return jsonify(transactions if transactions is not None else []) 
    except Exception as e:
        logging.error(f"[AJAX Transactions] Error: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500

def _generate_insights_thread(checkin_id):
    try:
        from insight_generator import generate_insights
        record, _ = database.get_facing_member_details(checkin_id)
        active_member_num = record.get('MemberNumber') 
        
        if not active_member_num: 
            insight_cache[checkin_id] = "Insights require a valid member number. Please enter one."
            logging.info(f"[INSIGHTS] No member number available for check-in {checkin_id} after potential revert, cannot generate insights.")
            return

        txs_by_account = transaction_cache.get(active_member_num, {})
        all_transactions = [tx for items in txs_by_account.values() if isinstance(items, list) for tx in filter_recent_transactions(items, INSIGHTS_TRANSACTION_DAYS)]

        logging.info(f"[INSIGHTS] Generating insights for check-in {checkin_id} (member {active_member_num}) using {len(all_transactions)} transactions...")
        insights_list = generate_insights(all_transactions)
        insight_cache[checkin_id] = "\n".join(insights_list) if insights_list else "No specific insights generated."
    except Exception as e:
        logging.error(f"[INSIGHTS] Insight generation failed for check-in {checkin_id}: {e}", exc_info=True)
        insight_cache[checkin_id] = "Error generating insights."

@app.route('/generate_insights/<int:checkin_id>', methods=['POST'])
def generate_insights_route(checkin_id):
    insight_cache.pop(checkin_id, None) 
    threading.Thread(target=_generate_insights_thread, args=(checkin_id,), daemon=True).start()
    return jsonify({'status': 'started'})

@app.route('/get_insights/<int:checkin_id>')
def get_insights_route(checkin_id):
    if checkin_id in insight_cache:
        return jsonify({'status': 'done', 'insights': insight_cache[checkin_id]})
    return jsonify({'status': 'pending'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('WAITING_PORT', 8082)), debug=app.config['DEBUG'])
