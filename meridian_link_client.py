from flask import current_app, render_template, flash
import requests
import xml.etree.ElementTree as ET
import logging
import traceback
import hashlib
import base64
import os
import xml.dom.minidom
import os


# Configure logging if not already configured by the main app
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MeridianLinkError(Exception):
    """Custom exception for MeridianLink client errors."""
    pass

class MeridianLinkClient:
    def __init__(self, logger, verify_ssl=False): # Removed config, added verify_ssl consistency
        # Load configuration directly from environment variables
        self.user_id = os.getenv('ML_API_USER_ID')
        self.password = os.getenv('ML_API_PASSWORD')
        self.api_url = os.getenv('ML_API_URL') # URL for SEARCH_QUERY
        self.get_loan_url = os.getenv('ML_API_GET_LOAN_URL') # URL for GET_LOAN

        self.logger = logger
        self.verify_ssl = verify_ssl # Added for consistency

        # Basic check for essential config
        if not all([self.user_id, self.password, self.api_url, self.get_loan_url]):
             self.logger.error("CRITICAL: Missing required MeridianLink environment variables (ML_API_USER_ID, ML_API_PASSWORD, ML_API_URL, ML_API_GET_LOAN_URL). Client may not function.")
             # Optionally raise an error or handle appropriately
             # raise MeridianLinkError("Missing required MeridianLink configuration.")

        # Log loaded config (mask password)
        self.logger.info(f"MeridianLinkClient Initialized:")
        self.logger.info(f"  User ID: {self.user_id}")
        self.logger.info(f"  Password: {'*' * len(self.password) if self.password else 'Not Set'}")
        self.logger.info(f"  Search API URL: {self.api_url}")
        self.logger.info(f"  Get Loan API URL: {self.get_loan_url}")
        self.logger.info(f"  Verify SSL: {self.verify_ssl}")

        # Disable SSL warnings if verification is off
        if not self.verify_ssl:
            import warnings
            import urllib3
            warnings.warn("MeridianLinkClient: SSL certificate verification is disabled.")
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


    # --- Static methods for encoding/decoding remain the same ---
    @staticmethod
    def encode_person_number(person_number):
        salt = os.urandom(16)
        combined = salt + str(person_number).encode()
        hashed = hashlib.sha256(combined).digest()
        encoded = base64.urlsafe_b64encode(salt + hashed).decode().rstrip('=')
        print(f"Encoded {person_number} to {encoded}")
        return encoded

    @staticmethod
    def decode_person_number(encoded):
        try:
            padding = '=' * (4 - (len(encoded) % 4))
            decoded = base64.urlsafe_b64decode(encoded + padding)
            salt, hashed = decoded[:16], decoded[16:]
            for i in range(1, 1000000):
                test_combined = salt + str(i).encode()
                if hashlib.sha256(test_combined).digest() == hashed:
                    print(f"Decoded {encoded} to {i}")
                    return str(i)
            raise ValueError("Invalid encoded person number")
        except Exception as e:
            print(f"Error decoding {encoded}: {str(e)}")
            raise

    def query_meridian_link(self, ssn):
        try:
            xml_payload = f"""
            <REQUEST>
                <LOGIN api_user_id="{self.user_id}" api_password="{self.password}"/>
                <SEARCH_QUERY borrower_ssn="{ssn}"/>
            </REQUEST>
            """
            self.logger.info(f"[ML_CLIENT_API_CALL] Attempting to query Meridian Link API for SSN ending: {ssn[-4:] if ssn else 'N/A'}")
            self.logger.debug(f"Request payload: {xml_payload}")

            # Use verify=self.verify_ssl
            response = requests.post(self.api_url, data=xml_payload, headers={'Content-Type': 'application/xml'}, verify=self.verify_ssl, timeout=30) # Added timeout
            response.raise_for_status()

            self.logger.info(f"[ML_CLIENT_API_SUCCESS] Successfully received API response from Meridian Link (Search) for SSN ending: {ssn[-4:] if ssn else 'N/A'}. Status code: {response.status_code}")
            self.logger.debug(f"Response content: {response.content}")
            
            root = ET.fromstring(response.content)
            search_results = root.find('.//SEARCH_RESULTS')
            
            if search_results is None or len(search_results) == 0:
                self.logger.warning(f"No loan applications found for SSN: {ssn}")
                return None
            
            loans = []
            for loan in search_results.findall('LOAN'):
                loan_data = {
                    'loan_type': loan.get('loan_type'),
                    'loan_id': loan.get('loan_id'),
                    'loan_num': loan.get('loan_num'),
                    'loan_status': loan.get('loan_status'),
                    'approval_date': loan.get('approval_date'),
                    'borrower_name': f"{loan.get('borrower_fname')} {loan.get('borrower_mname')} {loan.get('borrower_lname')}".strip(),
                    'created_date': loan.get('create_date'),  # Updated here
                    'last_modified_date': loan.get('last_modified_date'),
                    'booking_date': loan.get('booking_date')
                }
                loans.append(loan_data)
            
            self.logger.info(f"Successfully parsed Meridian Link data for SSN: {ssn}")
            self.logger.debug(f"Parsed result: {loans}")
            
            return loans
        except Exception as e:
            self.logger.error(f"Error querying Meridian Link API (Search): {str(e)}", exc_info=True)
            # flash(f"Error querying Meridian Link API: {str(e)}", "error") # Flashing should happen in the route handler
            return None # Return None on error

    def query_meridian_link_get_loan(self, loan_id):
        self.logger.debug(f"Entering query_meridian_link_get_loan method with loan_id: {loan_id}")

        try:
            xml_payload = self._prepare_get_loan_payload(loan_id)
            self.logger.debug(f"Prepared XML payload: {xml_payload}")

            response = self._make_api_request(xml_payload)
            self.logger.debug(f"Received API response with status code: {response.status_code}")

            parsed_result = self._parse_get_loan_response(response.content)
            self.logger.debug(f"Parsed result: {parsed_result}")

            if parsed_result:
                self.logger.info(f"Successfully retrieved and parsed loan details for loan_id: {loan_id}")
            else:
                self.logger.warning(f"Failed to parse loan details for loan_id: {loan_id}")

            return parsed_result
        except requests.RequestException as e:
            self.logger.error(f"Request to Meridian Link API failed: {str(e)}")
            return None
        except ET.ParseError as e:
            self.logger.error(f"XML parsing error: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error in query_meridian_link_get_loan: {str(e)}")
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            return None

    def _prepare_get_loan_payload(self, loan_id):
        return f"""
        <INPUT version="2.1">
            <LOGIN api_user_id="{self.user_id}" api_password="{self.password}"/>
            <REQUEST>
                <LOAN loan_id="{loan_id}" include_underwriting_info="Y"/>
            </REQUEST>
        </INPUT>
        """

    def _make_api_request(self, xml_payload):
        self.logger.info(f"[ML_CLIENT_API_CALL] Attempting to send GET LOAN request to Meridian Link API.")
        self.logger.debug(f"Request payload: {xml_payload}")

        # Use verify=self.verify_ssl
        response = requests.post(self.get_loan_url, data=xml_payload, headers={'Content-Type': 'application/xml'}, verify=self.verify_ssl, timeout=30) # Added timeout
        response.raise_for_status()

        self.logger.info(f"[ML_CLIENT_API_SUCCESS] Successfully received API response from Meridian Link (Get Loan). Status code: {response.status_code}")
        self.logger.debug(f"Response content: {response.content}")
        
        return response

    def _parse_get_loan_response(self, response_content):
        try:
            # Log the full XML response with pretty-printing
            pretty_xml = xml.dom.minidom.parseString(response_content).toprettyxml()
            self.logger.debug(f"Full XML Response:\n{pretty_xml}")

            root = ET.fromstring(response_content)
            self.logger.debug(f"Root element: {ET.tostring(root, encoding='utf8').decode('utf8')}")
            
            loan_data = root.find('.//RESPONSE/LOAN_DATA')
            if loan_data is None:
                self.logger.error("No LOAN_DATA element found in the XML response")
                return None
            
            result = {
                'loan_number': loan_data.get('loan_number', 'N/A'),
                'loan_type': loan_data.get('loan_type', 'N/A')
            }
            
            self.logger.debug(f"Initial parsed result: {result}")

            loan_type = result['loan_type']
            
            # Define namespaces
            namespaces = {
                'ns0': 'http://www.meridianlink.com/CLF',
                'ns1': 'http://www.meridianlink.com/InternalUse'
            }
            
            # Add parsing logic for PL loan type
            if loan_type == 'PL':
                loan_info = loan_data.find('.//ns0:PERSONAL_LOAN/ns0:APPLICANTS/ns0:APPLICANT', namespaces)
                if loan_info is not None:
                    result.update({
                        'credit_score': loan_info.get('credit_score', 'N/A')
                    })
                
                funding_info = loan_data.find('.//ns0:FUNDING', namespaces)
                if funding_info is not None:
                    result.update({
                        'funding_date': funding_info.get('funding_date', 'N/A'),
                        'amount_advanced': funding_info.get('amount_advanced', 'N/A')
                    })
            
            # Add parsing logic for VL loan type
            elif loan_type == 'VL':
                vehicle_info = loan_data.find('.//ns0:VEHICLE_LOAN/ns0:VEHICLES/ns0:VEHICLE', namespaces)
                if vehicle_info is not None:
                    result.update({
                        'vehicle_value': vehicle_info.get('vehicle_value', 'N/A')
                    })
                
                insurance_info = vehicle_info.find('.//ns0:INSURANCE', namespaces)
                if insurance_info is not None:
                    result.update({
                        'policy_number': insurance_info.get('policy_number', 'N/A')
                    })
                
                # Find insurance company name
                contact_info = loan_data.findall('.//ns0:CONTACT_INFO', namespaces)
                for contact in contact_info:
                    if contact.get('contact_type') == 'INSAGENT':
                        result.update({
                            'insurance_company': contact.get('company_name', 'N/A')
                        })
                        break
            
            # Add parsing logic for XA loan type
            elif loan_type == 'XA':
                account_info = loan_data.find('.//ns0:APPROVED_ACCOUNTS/ns0:ACCOUNT_TYPE', namespaces)
                if account_info is not None:
                    result.update({
                        'account_name': account_info.get('account_name', 'N/A'),
                        'amount_deposit': account_info.get('amount_deposit', 'N/A'),
                        'rate': account_info.get('rate', 'N/A')
                    })
            
            self.logger.info(f"Successfully parsed loan data")
            self.logger.debug(f"Parsed result: {result}")
            return result
        except ET.ParseError as e:
            self.logger.error(f"XML parsing error: {str(e)}")
            self.logger.error(f"Failed response content: {response_content}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error in _parse_get_loan_response: {str(e)}")
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            return None

    def _find_element(self, parent, path, namespaces):
        element = parent.find(path, namespaces)
        if element is None:
            self.logger.warning(f"Element not found: {path}")
        return element
