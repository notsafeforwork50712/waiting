@app.route('/api/member/<int:member_id>')
def get_member_data(member_id):
    """API endpoint to get member data for the dashboard modal."""
    try:
        # Get member record from the database
        record, error = database.get_facing_member_details(member_id)
        if error or not record:
            logging.warning(f"[API] Member record not found for member_id: {member_id}. Error: {error}")
            return jsonify({'error': 'Member not found'}), 404
        
        member_number = record.get('MemberNumber')
        if not member_number:
            logging.warning(f"[API] No MemberNumber for member_id: {member_id} in record: {record}")
            return jsonify({'error': 'No member number associated with this check-in'}), 400
        
        # Attempt to retrieve DNA data (from cache or API)
        dna_data = None
        if member_number in dna_cache:
            dna_data = dna_cache[member_number]
            logging.info(f"[API] DNA data for member {member_number} found in cache.")
        elif dna_client:
            try:
                dna_data = dna_client.get_person_detail_by_member_number(member_number)
                if dna_data:
                    dna_cache[member_number] = dna_data
                    logging.info(f"[API] DNA data for member {member_number} fetched from API and cached.")
                else:
                    logging.warning(f"[API] No DNA data returned from API for member {member_number}.")
            except Exception as e:
                logging.error(f"[API] Error fetching DNA data for member {member_number}: {e}", exc_info=True)
        else:
            logging.info(f"[API] DNA client not available, skipping DNA data fetch for member {member_number}.")

        # Attempt to retrieve MeridianLink (ML) data if DNA data (especially SSN) is available
        ml_data = None
        if dna_data and dna_data.get('ssn') and ml_client:
            try:
                ml_data = ml_client.query_meridian_link(dna_data['ssn'])
                logging.info(f"[API] ML data for SSN (member {member_number}) fetched. Found {len(ml_data) if ml_data else 0} items.")
            except Exception as e:
                logging.error(f"[API] Error fetching MeridianLink data for member {member_number}: {e}", exc_info=True)
        elif not (dna_data and dna_data.get('ssn')):
             logging.info(f"[API] Skipping ML data fetch for member {member_number} due to missing DNA data or SSN.")
        elif not ml_client:
            logging.info(f"[API] ML client not available, skipping ML data fetch for member {member_number}.")

        # Initialize lists/dictionaries for the JSON response
        response_accounts = []
        response_transactions = {}
        
        # Process DNA accounts (Shares, Checking, etc.)
        if dna_data and isinstance(dna_data.get('accounts'), list):
            for acc_detail_dict in dna_data.get('accounts', []): 
                try:
                    acc_num = acc_detail_dict.get('account_number')
                    acc_type = acc_detail_dict.get('account_type', 'Account')
                    acc_balance = acc_detail_dict.get('balance', '0.00')
                    
                    account_key_string = f"{acc_type} - ${acc_balance}"
                    response_accounts.append(account_key_string)
                    
                    member_transactions_in_cache = transaction_cache.get(member_number, {})
                    if acc_num and acc_num in member_transactions_in_cache:
                        # Ensure transactions are formatted as strings if they are not already
                        raw_txns = member_transactions_in_cache[acc_num][:8]
                        formatted_txns = [str(tx) for tx in raw_txns] # Example: ensure all are strings
                        response_transactions[account_key_string] = formatted_txns
                    else:
                        response_transactions[account_key_string] = []
                except Exception as e:
                    logging.error(f"[API] Error processing DNA account detail {acc_detail_dict} for member {member_number}: {e}", exc_info=True)
        
        # Process MeridianLink (ML) loan accounts
        if ml_data and isinstance(ml_data, list):
            for loan_detail_dict in ml_data:
                try:
                    loan_type = loan_detail_dict.get('loan_type', 'Loan')
                    loan_num = loan_detail_dict.get('loan_num', '') 
                    
                    account_key_string = f"{loan_type} #{loan_num}"
                    response_accounts.append(account_key_string)
                    
                    if account_key_string not in response_transactions:
                        response_transactions[account_key_string] = []
                except Exception as e:
                    logging.error(f"[API] Error processing ML loan detail {loan_detail_dict} for member {member_number}: {e}", exc_info=True)

        # Ensure all accounts listed in response_accounts have a corresponding transaction list
        for key_str in response_accounts:
            if key_str not in response_transactions:
                response_transactions[key_str] = []
                
        # Get cached AI insights
        insights_list = []
        if member_id in insight_cache: # member_id is the checkin_id
            insights_text = insight_cache[member_id]
            if isinstance(insights_text, str):
                insights_list = insights_text.split('\n')
            elif isinstance(insights_text, list):
                insights_list = insights_text
            logging.info(f"[API] Insights for check-in {member_id} (member {member_number}) found in cache.")

        # Construct member_info, preferring DNA data but falling back to DB record
        member_name = record.get('Name', 'Unknown Member') 
        if dna_data:
            firstname = dna_data.get('firstname', '')
            lastname = dna_data.get('lastname', '')
            if firstname or lastname: 
                 member_name = f"{firstname} {lastname}".strip()
        
        member_info_data = {
            'name': member_name,
            'member_number': member_number
        }
        if dna_data: 
            for key in ['ssn', 'birth_date', 'email', 'phone_home', 'phone_cell', 'address_line1', 'city', 'state', 'zip_code']:
                if dna_data.get(key):
                    member_info_data[key] = dna_data[key]
        
        logging.info(f"[API] Successfully prepared data for member_id: {member_id} (MemberNumber: {member_number}).")
        
        return jsonify({
            'accounts': response_accounts,
            'transactions': response_transactions,
            'insights': insights_list[:4], 
            'member_info': member_info_data
        })
        
    except Exception as e:
        logging.critical(f"[API] UNHANDLED EXCEPTION in get_member_data for member_id {member_id}: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
