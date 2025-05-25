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
        
        # Get DNA data from cache or API
        dna_data = None
        if member_number in dna_cache:
            dna_data = dna_cache[member_number]
        elif dna_client:
            try:
                dna_data = dna_client.get_person_detail_by_member_number(member_number)
                if dna_data:
                    dna_cache[member_number] = dna_data
            except Exception as e:
                logging.error(f"[API] Error fetching DNA data for member {member_number}: {e}")
        
        # Get MeridianLink data from API if applicable
        ml_data = None
        if dna_data and dna_data.get('ssn') and ml_client:
            try:
                ml_data = ml_client.query_meridian_link(dna_data['ssn'])
            except Exception as e:
                logging.error(f"[API] Error fetching MeridianLink data for member {member_number} with SSN ending {dna_data.get('ssn', '')[-4:]}: {e}")

        # Initialize response fields
        response_accounts = []
        response_transactions = {}
        
        # Process DNA accounts
        if dna_data and dna_data.get('accounts'):
            for acc_detail_dict in dna_data.get('accounts', []):
                acc_num = acc_detail_dict.get('account_number')
                acc_type = acc_detail_dict.get('account_type', 'Account')
                acc_balance = acc_detail_dict.get('balance', '0.00')
                account_key_string = f"{acc_type} - ${acc_balance}"
                response_accounts.append(account_key_string)

                # Get transactions for this DNA account
                member_tx_cache_for_member = transaction_cache.get(member_number, {})
                if acc_num in member_tx_cache_for_member:
                    response_transactions[account_key_string] = member_tx_cache_for_member[acc_num][:8]
                else:
                    response_transactions[account_key_string] = []
            
        # Process MeridianLink (ML) loan accounts
        if ml_data:
            for loan_detail_dict in ml_data:
                loan_type = loan_detail_dict.get('loan_type', 'Loan')
                loan_num = loan_detail_dict.get('loan_num', '')
                account_key_string = f"{loan_type} #{loan_num}"
                response_accounts.append(account_key_string)
                
                # Loans from ML typically don't have transactions listed in the same way,
                # so initialize with an empty list if not already populated (e.g. if it was also a DNA account)
                if account_key_string not in response_transactions:
                    response_transactions[account_key_string] = []

        # Fallback: Ensure all accounts in response_accounts have a key in response_transactions
        for key_string in response_accounts:
            if key_string not in response_transactions:
                response_transactions[key_string] = []

        # Get cached insights
        insights = []
        if member_id in insight_cache:
            insights_text = insight_cache[member_id]
            insights = insights_text.split('\n') if insights_text else []
        
        return jsonify({
            'accounts': response_accounts,
            'transactions': response_transactions,
            'insights': insights[:4],  # Limit to 4 for UI
            'member_info': {
                'name': dna_data.get('firstname', '') + ' ' + dna_data.get('lastname', '') if dna_data else record.get('Name', ''),
                'member_number': member_number
            }
        })
        
    except Exception as e:
        logging.error(f"[API] Error in get_member_data for member {member_id}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500
