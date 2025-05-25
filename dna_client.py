import os
import requests
import xml.etree.ElementTree as ET
import logging
from datetime import datetime, timedelta
import html
import uuid
import warnings
import traceback
from requests.adapters import HTTPAdapter
import xml.dom.minidom as minidom
from flask import current_app 
import base64
import hashlib

# Configure logging if not already configured by the main app
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DNAApiError(Exception):
    pass


class DNAApiClient:
    def __init__(self, logger, verify_ssl=False):
        # Load configuration directly from environment variables
        self.pie_endpoint = os.getenv('PIE_ENDPOINT')
        self.dna_endpoint = os.getenv('DNA_ENDPOINT')
        self.device_id = os.getenv('DEVICE_ID')
        self.prod_env_cd = os.getenv('PROD_ENV_CD') 
        self.prod_def_cd = os.getenv('PROD_DEF_CD')    
        self.user_id = os.getenv('USER_ID')
        self.password = os.getenv('PASSWORD')
        self.application_id = os.getenv('APPLICATION_ID')
        self.ntwk_node_name = os.getenv('NTWK_NODE_NAME')

        # Instance variables
        self.sso_ticket = None
        self.whois_response = None
        self.auth_expiration = None
        self.logger = logger
        self.verify_ssl = verify_ssl
        self.session = self._create_retry_session()
        self.transaction_type_descriptions = {
            'CDSB': 'Cost Disbursement',
            'CRCT': 'Cost Receipt',
            'FRCT': 'Fee Receipt',
            'FDSB': 'Fee Disbursement',
            'CHAS': 'Charge Assessment',
            'CHST': 'Charge Satisfaction',
            'LCAP': 'Loan Charge Capitalization',
            'PARS': 'Participant Sold',
            'CLS': 'Closeout Withdrawal',
            'INT': 'Interest',
            'PEN': 'Penalty',
            'IW': 'Interest Withholding',
            'SW': 'State Withholding',
            'FW': 'Federal Withholding',
            'FIN': 'Financed Insurance',
            'FEE': 'Loan Fees',
            'COST': 'Loan Costs',
            'SINS': 'Simple Insurance',
            'MINS': 'Pass Thru Insurance',
            'RFEE': 'Reoccurring Fees',
            'DLR': 'Dealer Loans',
            'CHRG': 'Loan Charges',
            'BYDN': 'Buydown Subsidizing',
            'DEP': 'Deposit',
            'WTH': 'Withdraw',
            'SPMT': 'Regular Payment',
            'CI': 'Check Issue',
            'GLR': 'General Ledger Receipt',
            'FWDP': 'Fedwire Deposit',
            'FWDB': 'Fedwire Withdrawal',
            'SFDP': 'SWIFT Wire Deposit',
            'SFDB': 'SWIFT Wire Withdrawal',
            'RTDP': 'Real Time Payment Deposit',
            'RTDB': 'Real Time Payment Withdrawal',
            'GLD': 'General Ledger Disbursement',
            'FWSF': 'Fedwire Service Fee',
            'SFSF': 'SWIFT Wire Service Fee',
            'RTSF': 'Real Time Payment Service Fee',
            'FWR': 'Fedwire',
            'SWF': 'SWIFT',
            'UCFD': 'Overdraft Protection Deposit',
            'RTP': 'Real Time Payment',
            'BOOK': 'Book Transfer'
        }

        if not self.verify_ssl:
            warnings.warn("SSL certificate verification is disabled.")
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

    def _create_retry_session(self):
        session = requests.Session()
        retries = 3
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    def prettify_xml(self, xml_string):
        try:
            if isinstance(xml_string, str):
                xml_string = xml_string.encode('utf-8')
            parsed = minidom.parseString(xml_string)
            pretty_xml = parsed.toprettyxml(indent="  ")
            # Remove empty lines
            return os.linesep.join([s for s in pretty_xml.splitlines() if s.strip()])
        except Exception as e:
            self.logger.error(f"Failed to prettify XML: {str(e)}")
            # Ensure we return a string even on error
            return xml_string.decode('utf-8', errors='ignore') if isinstance(xml_string, bytes) else str(xml_string)


    def log_xml_response(self, response_text):
        """Log XML response, splitting long responses into a file."""
        try:
            pretty_xml = self.prettify_xml(response_text)
            lines = pretty_xml.splitlines()
            if len(lines) > 50:
                self.logger.debug("--- Start XML Response (Truncated) ---")
                for line in lines[:50]:
                    self.logger.debug(line)
                self.logger.debug("--- End XML Response (Truncated) ---")
                log_dir = 'DNA_response_logs'
                if not os.path.exists(log_dir):
                    try:
                        os.makedirs(log_dir)
                    except OSError as e:
                        self.logger.error(f"Could not create log directory {log_dir}: {e}")
                        self.logger.debug(f"Raw XML Response:\n{response_text}")
                        return
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                file_path = os.path.join(log_dir, f'full_response_{timestamp}.xml')
                try:
                    with open(file_path, 'w', encoding='utf-8') as file:
                        file.write(pretty_xml)
                    self.logger.debug(f'Full XML response saved to {file_path}')
                except IOError as e:
                    self.logger.error(f"Could not write full XML response to {file_path}: {e}")
                    self.logger.debug(f"Raw XML Response:\n{response_text}")
            else:
                self.logger.debug(f"XML Response:\n{pretty_xml}")
        except Exception as e:
             self.logger.error(f"Error logging/prettifying XML response: {e}")
             self.logger.debug(f"Raw XML Response:\n{response_text}")

    def _make_request(self, url, headers, data):
        try:
            self.logger.debug(f"Making request to {url}")
            self.logger.debug(f"Headers: {headers}")
            self.logger.debug(f"Request data: {self.prettify_xml(data)}")

            # Increase timeout to 60 seconds for better reliability
            response = self.session.post(url, headers=headers, data=data, timeout=60, verify=self.verify_ssl)

            self.logger.info(f"API called: POST {url}")
            self.logger.debug(f"Response status code: {response.status_code}")
            self.logger.debug(f"Response headers: {response.headers}")
            
            self.log_xml_response(response.text)

            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            return response
        except requests.ConnectTimeout as e:
            self.logger.error(f"Connection timeout to DNA API: {str(e)}")
            self.logger.error(f"Could not connect to {url} - server may be down or unreachable")
            return None
        except requests.ReadTimeout as e:
            self.logger.error(f"Read timeout from DNA API: {str(e)}")
            self.logger.error(f"Server at {url} took too long to respond")
            return None
        except requests.exceptions.HTTPError as e:
             # Log HTTP errors (like 4xx, 5xx) but return None as the call technically completed but failed
             self.logger.error(f"HTTP error during API request: {str(e)}")
             if e.response is not None:
                 self.logger.error(f"Response status code: {e.response.status_code}")
                 self.logger.error(f"Response headers: {e.response.headers}")
                 self.log_xml_response(e.response.text) # Log the error response body
             return None
        except requests.RequestException as e:
            self.logger.error(f"General API request failed: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                self.logger.error(f"Response status code: {e.response.status_code}")
                self.logger.error(f"Response headers: {e.response.headers}")
                self.log_xml_response(e.response.text)
            return None
        except Exception as e: # Catch any other unexpected errors
            self.logger.error(f"Unexpected error during API request: {str(e)}", exc_info=True)
            return None


    def authenticate(self):
        self.logger.info("Starting authentication process")
        try:
            login_data = self._prepare_login_data()
            login_headers = {
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': '"http://www.opensolutions.com/DirectSignon"'
            }
            login_response = self._make_request(self.pie_endpoint, login_headers, login_data)
            if login_response is None:
                self.logger.error("Authentication failed: Connection to DNA API timed out or request failed.")
                return False
                
            self.logger.debug(f"Login response content: {self.prettify_xml(login_response.content)}")
            self.sso_ticket = self._parse_authentication_response(login_response.content)
            if not self.sso_ticket:
                self.logger.error("Failed to obtain SSO ticket from response")
                return False
                
            self.logger.info("Successfully obtained SSO ticket")

            whois_data = self._prepare_whois_data()
            whois_headers = {
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': '"http://www.opensolutions.com/WhoIs"'
            }
            whois_response = self._make_request(self.pie_endpoint, whois_headers, whois_data)
            if whois_response is None:
                self.logger.error("Authentication failed: WhoIs request to DNA API timed out or request failed.")
                return False
                
            self.logger.debug(f"WhoIs response content: {self.prettify_xml(whois_response.content)}")
            self.whois_response = self._parse_whois_response(whois_response.content)
            if not self.whois_response:
                self.logger.error("Failed to obtain WhoIs response from response")
                return False

            self.auth_expiration = datetime.now() + timedelta(hours=1)
            self.logger.info("Authentication successful")
            return True
        except Exception as e:
            self.logger.error(f"Authentication failed: {str(e)}", exc_info=True)
            return False

    def _prepare_login_data(self):
        if not all([self.device_id, self.user_id, self.password, self.prod_env_cd, self.prod_def_cd]):
            self.logger.error("Missing required authentication parameters")
            raise DNAApiError("Missing required authentication parameters")

        # Construct the inner XML request first
        inner_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<DirectSSORequest MessageDateTime="{datetime.now().isoformat()}" TrackingId="{str(uuid.uuid4())}">
  <DeviceId>{html.escape(self.device_id)}</DeviceId>
  <UserId>{html.escape(self.user_id)}</UserId>
  <Password>{html.escape(self.password)}</Password>
  <ProdEnvCd>{html.escape(self.prod_env_cd)}</ProdEnvCd>
  <ProdDefCd>{html.escape(self.prod_def_cd)}</ProdDefCd>
</DirectSSORequest>"""
        
        # Escape the entire inner XML string before embedding it
        return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <DirectSignon xmlns="http://www.opensolutions.com/">
      <xmlRequest>{html.escape(inner_xml)}</xmlRequest>
    </DirectSignon>
  </soap:Body>
</soap:Envelope>"""

    def _prepare_whois_data(self):
        if not self.sso_ticket:
            self.logger.error("SSO ticket is missing")
            raise DNAApiError("SSO ticket is missing")

        # Construct the inner XML request first
        inner_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<WhoIsRequest MessageDateTime="{datetime.now().isoformat()}" TrackingId="{str(uuid.uuid4())}" SSOTicket="{html.escape(self.sso_ticket)}">
  <LookupSSOTicket>{html.escape(self.sso_ticket)}</LookupSSOTicket>
</WhoIsRequest>"""
        
        # Escape the entire inner XML string before embedding it
        return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <WhoIs xmlns="http://www.opensolutions.com/">
      <xmlRequest>{html.escape(inner_xml)}</xmlRequest>
    </WhoIs>
  </soap:Body>
</soap:Envelope>"""

    def _parse_authentication_response(self, response_content):
        try:
            root = ET.fromstring(response_content)
            self.logger.debug(f"Authentication response XML: {self.prettify_xml(ET.tostring(root, encoding='unicode'))}")
            
            direct_signon_result = root.find('.//{http://www.opensolutions.com/}DirectSignonResult')
            if direct_signon_result is not None and direct_signon_result.text:
                direct_sso_response = ET.fromstring(direct_signon_result.text)
                sso_ticket_element = direct_sso_response.find('.//SSOTicket')
                if sso_ticket_element is not None:
                    return sso_ticket_element.text
            
            self.logger.error("Failed to find SSOTicket in the authentication response")
            return None
        except ET.ParseError as e:
            self.logger.error(f"Failed to parse authentication response XML: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error parsing authentication response: {str(e)}", exc_info=True)
            return None


    def _parse_whois_response(self, response_content):
        try:
            root = ET.fromstring(response_content)
            self.logger.debug(f"WhoIs response XML: {self.prettify_xml(ET.tostring(root, encoding='unicode'))}")
            
            whois_result = root.find('.//{http://www.opensolutions.com/}WhoIsResult')
            if whois_result is not None:
                return whois_result.text
            
            self.logger.error("Failed to find WhoIsResult in the WhoIs response")
            return None
        except ET.ParseError as e:
            self.logger.error(f"Failed to parse WhoIs response XML: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error parsing WhoIs response: {str(e)}", exc_info=True)
            return None

    def ensure_authentication(self):
        if not self.sso_ticket or not self.whois_response or datetime.now() >= self.auth_expiration:
            self.logger.info("Authentication required. Starting authentication process.")
            auth_success = self.authenticate()
            if not auth_success:
                self.logger.warning("Authentication failed. DNA API features will be unavailable.")
                return False
            return auth_success
        else:
            self.logger.debug("Using existing authentication.")
            return True
            
    def _prepare_submit_request_envelope(self, request_body):
        """
        Prepares the SOAP envelope for a SubmitRequest call to the DNA API.
        This is used by various methods that need to make API calls to the DNA endpoint.
        
        Args:
            request_body: The specific request body XML for the API call
            
        Returns:
            The complete XML request string, or None if authentication details are missing
        """
        if not self.application_id or not self.ntwk_node_name or not self.whois_response:
            self.logger.error("Missing required parameters for API request")
            return None
            
        return f"""<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <SubmitRequest xmlns="http://www.opensolutions.com/CoreApi">
      <input xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
        <Input>
          <ExtensionRequests i:nil="true" />
          <Requests>
            {request_body}
          </Requests>
          <UserAuthentication>
            <ApplID>{html.escape(self.application_id)}</ApplID>
            <ApplNumber>0</ApplNumber>
            <AuthorizationType>SingleSignOn</AuthorizationType>
            <NetworkNodeName>{html.escape(self.ntwk_node_name)}</NetworkNodeName>
            <Password>{html.escape(self.whois_response)}</Password>
          </UserAuthentication>
        </Input>
        <ShouldCommitOrRollback>false</ShouldCommitOrRollback>
      </input>
    </SubmitRequest>
  </s:Body>
</s:Envelope>"""


    # Get Person Number by Member Number ---
    def get_person_number_by_member_number(self, member_number):
        """
        Fetches person details using Member Number (ReqTypCd 7711) and returns the Person Number.
        Returns None if the API call fails due to connection issues or if the person is not found.
        """
        self.logger.info(f"Attempting to fetch person details by member number: {member_number} using ReqTypCd 7711")
        try:
            if not self.ensure_authentication():
                return None # Authentication failed
        except Exception as auth_err:
            self.logger.warning(f"DNA authentication failed before getting person number {member_number}: {auth_err}")
            return None

        # Construct the request body for PersonDetailInquiryRequest (7711) using Member Number attribute
        request_body = f"""
            <RequestBase i:type="PersonDetailInquiryRequest" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
              <Person memberNbr="{html.escape(str(member_number))}" />
              <RequestTypeCode>7711</RequestTypeCode>
            </RequestBase>"""

        full_request_xml = self._prepare_submit_request_envelope(request_body)
        if full_request_xml is None:
            self.logger.warning(f"Failed to prepare request envelope for member number {member_number}")
            return None
            
        headers = {
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': '"http://www.opensolutions.com/CoreApi/ICoreApiService/SubmitRequest"'
        }

        try:
            response = self._make_request(self.dna_endpoint, headers, full_request_xml)
            if response is None:
                self.logger.warning(f"API request failed when fetching person details for member number {member_number}")
                return None

            # Parse the response to extract the Person element
            try:
                root = ET.fromstring(response.content)
            except Exception as parse_error:
                self.logger.error(f"Failed to parse XML response for member {member_number}: {parse_error}")
                return None
                
            # Define namespaces used in the response
            namespaces = {
                's': 'http://schemas.xmlsoap.org/soap/envelope/',
                'core': 'http://www.opensolutions.com/CoreApi',
                'a': 'http://schemas.datacontract.org/2004/07/OpenSolutions.CoreApiService.Services.Messages',
                'cmn': 'http://schemas.datacontract.org/2004/07/OpenSolutions.CoreApiService.Services.Messages.Common',
                'i': 'http://www.w3.org/2001/XMLSchema-instance'
            }
            
            # Find the correct ResponseBase
            response_base = None
            for resp in root.findall('.//core:Responses/core:ResponseBase', namespaces):
                if resp.get('{' + namespaces['i'] + '}type') == 'PersonDetailInquiryResponse':
                    response_base = resp
                    break
            
            if response_base is None:
                self.logger.warning("Could not find PersonDetailInquiryResponse in the 7711 response.")
                return None

            was_successful_elem = response_base.find('a:WasSuccessful', namespaces)
            if was_successful_elem is None or was_successful_elem.text.lower() != 'true':
                error_message = "DNA API response indicates failure for ReqTypCd 7711."
                errors_elem = response_base.find('a:Errors', namespaces)
                if errors_elem is not None:
                    for error in errors_elem.findall('a:Error', namespaces):
                        err_msg = self.safe_find(error, 'a:ErrorMessage', namespaces)
                        if err_msg:
                             error_message += f" Message: {err_msg}"
                self.logger.warning(error_message)
                return None 

            # Person data is directly under ResponseBase for 7711
            person_elem = response_base.find('a:Person', namespaces)
            if person_elem is not None:
                persnbr = person_elem.get('persNbr') # Get persNbr attribute
                if persnbr:
                    self.logger.info(f"Successfully found Person Number {persnbr} for Member Number {member_number} via 7711.")
                    return persnbr
                else:
                    self.logger.warning(f"Found Person element but missing 'persNbr' attribute for Member Number {member_number}.")
                    return None
            else:
                self.logger.warning(f"No Person element found in successful 7711 response for Member Number {member_number}")
                return None 

        except Exception as e:
            self.logger.error(f"Unexpected error processing 7711 response for member {member_number}: {str(e)}", exc_info=True)
            return None 


    # ---Get TaxId Data by Person Number ---
    # Note: This method is kept for reference but get_member_info_by_member_number (Method 3) is preferred
    def get_taxid_data_by_person_number(self, persnbr):
        """
        Fetches detailed member info including accounts using Person Number (ReqTypCd 7725, Method 4).
        Returns None if the API call fails due to connection issues or if data is not found/parsed.
        """
        self.logger.info(f"Attempting to fetch TaxId data by person number: {persnbr} using ReqTypCd 7725 / Method 4")
        try:
            if not self.ensure_authentication():
                return None # Authentication failed
        except Exception as auth_err:
            self.logger.warning(f"DNA authentication failed before getting TaxId data for person {persnbr}: {auth_err}")
            return None

        # Construct the request body for GetTaxIdDataRequest (7725) using Person Number (Method 4)
        request_body = f"""
            <RequestBase i:type="GetTaxIdDataRequest" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
              <MethodNumber>4</MethodNumber>
              <ReferenceNumber>{html.escape(str(persnbr))}</ReferenceNumber>
              <RequestTypeCode>7725</RequestTypeCode>
            </RequestBase>"""

        full_request_xml = self._prepare_submit_request_envelope(request_body)
        if full_request_xml is None:
             self.logger.warning(f"Failed to prepare request envelope for person number {persnbr}")
             return None
             
        headers = {
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': '"http://www.opensolutions.com/CoreApi/ICoreApiService/SubmitRequest"'
        }

        try:
            response = self._make_request(self.dna_endpoint, headers, full_request_xml)
            if response is None:
                self.logger.warning(f"API request failed when fetching TaxId data for person number {persnbr}")
                return None

            return self.parse_member_info(response.content)
        except Exception as e: 
            self.logger.error(f"Unexpected error getting TaxId data for person {persnbr}: {str(e)}", exc_info=True)
            return None

    def parse_member_info(self, response_content):
        """Parses the GetTaxIdDataResponse (7725) to extract member details."""
        self.logger.debug("Parsing member info from response")
        try:
            root = ET.fromstring(response_content)
            self.logger.debug(f"Response XML: {self.prettify_xml(ET.tostring(root, encoding='unicode'))}")

            namespaces = {
                's': 'http://schemas.xmlsoap.org/soap/envelope/',
                'core': 'http://www.opensolutions.com/CoreApi', 
                'a': 'http://schemas.datacontract.org/2004/07/OpenSolutions.CoreApiService.Services.Messages',
                'i': 'http://www.w3.org/2001/XMLSchema-instance'
                # Add other namespaces if needed 
            }

            # 1. Check overall success in UserAuthentication first
            user_auth_elem = root.find('.//core:UserAuthentication', namespaces)
            if user_auth_elem is None:
                 self.logger.error("Parser Error: Could not find 'core:UserAuthentication' element.")
                 return None

            overall_successful_elem = user_auth_elem.find('core:WasSuccessful', namespaces)
            if overall_successful_elem is None or overall_successful_elem.text.lower() != 'true':
                error_message = "Overall DNA API request failed (UserAuthentication WasSuccessful is not 'true')."
                errors_elem = user_auth_elem.find('core:Errors', namespaces)
                if errors_elem is not None:
                    for error in errors_elem.findall('core:Error', namespaces):
                        err_msg = self.safe_find(error, 'core:ErrorMessage', namespaces) 
                        if err_msg:
                             error_message += f" Message: {err_msg}"
                self.logger.error(error_message)
                return None # Overall request failed

            # 2. If overall request was successful, find the specific GetTaxIdDataResponse
            self.logger.debug("Overall UserAuthentication was successful. Looking for GetTaxIdDataResponse.")
            response_base = None
            for resp in root.findall('.//core:Responses/core:ResponseBase', namespaces):
                if resp.get('{' + namespaces['i'] + '}type') == 'GetTaxIdDataResponse':
                    response_base = resp
                    break

            if response_base is None:
                self.logger.error("Overall request successful, but could not find GetTaxIdDataResponse element.")
                return None

            # 3. Now parse the content within the found response_base
            specific_successful_elem = response_base.find('a:WasSuccessful', namespaces)
            if specific_successful_elem is not None and specific_successful_elem.text.lower() != 'true':
                 self.logger.warning("Overall request successful, but GetTaxIdDataResponse internal WasSuccessful is not 'true'. Parsing will proceed but might be incomplete.")
           

        
            # --- NAMESPACE FOR FINDING PERSON ELEMENT ---
            self.logger.debug("Attempting to find 'core:Person' directly under GetTaxIdDataResponse.")
            person_data = response_base.find('core:Person', namespaces) # Use 'core' namespace
            if person_data is None:
                 self.logger.error("Could not find 'core:Person' element directly under GetTaxIdDataResponse.")
                 # Log the structure of response_base for debugging if Person is missing
                 self.logger.debug(f"Structure of response_base:\n{self.prettify_xml(ET.tostring(response_base, encoding='unicode'))}")
                 return None

       
        
            # Try finding elements using core: prefix first, then a:, then no prefix as fallback
            persnbr = self.safe_find(person_data, 'core:PersonNumber', namespaces) or self.safe_find(person_data, 'a:PersonNumber', namespaces) or person_data.get('persNbr') # Also check attribute
            firstname = self.safe_find(person_data, 'core:FirstName', namespaces) or self.safe_find(person_data, 'a:FirstName', namespaces)
            lastname = self.safe_find(person_data, 'core:LastName', namespaces) or self.safe_find(person_data, 'a:LastName', namespaces)
            fullname = f"{firstname or ''} {lastname or ''}".strip()

            is_deceased_raw = self.safe_find(person_data, 'core:IsDeceased', namespaces) or self.safe_find(person_data, 'a:IsDeceased', namespaces)
            last_updated = self.safe_find(person_data, 'core:LastUpdated', namespaces) or self.safe_find(person_data, 'a:LastUpdated', namespaces)
            self.logger.debug(f"Raw IsDeceased value from API: {is_deceased_raw}")

            date_birth = self.safe_find(person_data, 'core:DateBirth', namespaces) or self.safe_find(person_data, 'a:DateBirth', namespaces)
            age = self.calculate_age(date_birth) if date_birth else None

            # Address Parsing (assuming structure like core:Addresses/core:Address)
            primary_address = None
            addresses_elem = person_data.find('core:Addresses', namespaces) or person_data.find('a:Addresses', namespaces)
            if addresses_elem is not None:
                 for address in addresses_elem.findall('core:Address', namespaces) or addresses_elem.findall('a:Address', namespaces):
                   
                     address_use_code = address.get('AddrUseCd') or self.safe_find(address, 'core:AddressUseCode', namespaces) or self.safe_find(address, 'a:AddressUseCode', namespaces)
                     if address_use_code == 'PRI':
                         primary_address = address
                         break

            address_str = None
            city = state = zip_code = None
            line1 = None
            if primary_address is not None:
                addr_lines_elem = primary_address.find('core:AddressLines', namespaces) or primary_address.find('a:AddressLines', namespaces)
                if addr_lines_elem is not None:
                    line_elem = addr_lines_elem.find('core:AddressLine', namespaces) or addr_lines_elem.find('a:AddressLine', namespaces)
              
                    line1 = self.safe_find(line_elem, '.', namespaces) if line_elem is not None else None

                city = self.safe_find(primary_address, 'core:CityName', namespaces) or self.safe_find(primary_address, 'a:CityName', namespaces)
                state = self.safe_find(primary_address, 'core:State', namespaces) or self.safe_find(primary_address, 'a:State', namespaces)
                zip_code = self.safe_find(primary_address, 'core:ZipCode', namespaces) or self.safe_find(primary_address, 'a:ZipCode', namespaces) or self.safe_find(primary_address, 'core:ZipCd', namespaces) or self.safe_find(primary_address, 'a:ZipCd', namespaces)
                address_str = f"{line1 or ''}, {city or ''}, {state or ''} {zip_code or ''}".strip(', ')

     
            email = None
            email_addresses_elem = person_data.find('core:EmailAddresses', namespaces) or person_data.find('a:EmailAddresses', namespaces)
            if email_addresses_elem is not None:
                 for email_address in email_addresses_elem.findall('core:EmailAddress', namespaces) or email_addresses_elem.findall('a:EmailAddress', namespaces):
                     email = self.safe_find(email_address, 'core:Email', namespaces) or self.safe_find(email_address, 'a:Email', namespaces)
                     if email: break

            # Phone number parsing
            home_phone = None
            cell_phone = None
            phone_number = None  # Initialize phone_number
            phones_elem = person_data.find('core:PersonPhones', namespaces) or person_data.find('a:PersonPhones', namespaces)
            if phones_elem is not None:
                for phone in phones_elem.findall('core:GetTaxIdDataPhone', namespaces) or phones_elem.findall('a:GetTaxIdDataPhone', namespaces):
                    usage_code = self.safe_find(phone, 'core:UsageCode', namespaces) or self.safe_find(phone, 'a:UsageCode', namespaces)
                    area_code = self.safe_find(phone, 'core:AreaCode', namespaces) or self.safe_find(phone, 'a:AreaCode', namespaces)
                    exchange = self.safe_find(phone, 'core:Exchange', namespaces) or self.safe_find(phone, 'a:Exchange', namespaces)
                    number = self.safe_find(phone, 'core:Number', namespaces) or self.safe_find(phone, 'a:Number', namespaces)
                    if area_code and exchange and number:
                        phone_number = f"{area_code}{exchange}{number}"
                        if usage_code == 'PER':
                            home_phone = phone_number
                        elif usage_code == 'BUS':
                            cell_phone = phone_number

            # Address parsing
            address_str = None
            city = state = zip_code = None
            line1 = None
            addresses_elem = person_data.find('core:PersonAddresses', namespaces) or person_data.find('a:PersonAddresses', namespaces)
            if addresses_elem is not None:
                address = addresses_elem.find('core:GetTaxIdDataPersonOrganizationAddress', namespaces) or addresses_elem.find('a:GetTaxIdDataPersonOrganizationAddress', namespaces)
                if address is not None:
                    addr_lines_elem = address.find('core:AddressLines', namespaces) or address.find('a:AddressLines', namespaces)
                    if addr_lines_elem is not None:
                        line_elem = addr_lines_elem.find('core:GetTaxIdDataAddressLine', namespaces) or addr_lines_elem.find('a:GetTaxIdDataAddressLine', namespaces)
                        if line_elem is not None:
                            line1 = self.safe_find(line_elem, 'core:AddressLineText', namespaces) or self.safe_find(line_elem, 'a:AddressLineText', namespaces)

                    city = self.safe_find(address, 'core:CityName', namespaces) or self.safe_find(address, 'a:CityName', namespaces)
                    state = self.safe_find(address, 'core:State', namespaces) or self.safe_find(address, 'a:State', namespaces)
                    zip_code = self.safe_find(address, 'core:ZipCode', namespaces) or self.safe_find(address, 'a:ZipCode', namespaces) or self.safe_find(address, 'core:ZipCd', namespaces) or self.safe_find(address, 'a:ZipCd', namespaces)
                    address_str = f"{line1 or ''}, {city or ''}, {state or ''} {zip_code or ''}".strip(', ')

        
            person_types_elem = person_data.find('core:PersonTypes', namespaces) or person_data.find('a:PersonTypes', namespaces)
            is_employee = False
            if person_types_elem is not None:
                 person_types = person_types_elem.findall('core:PersonType', namespaces) or person_types_elem.findall('a:PersonType', namespaces)
                 is_employee = any((self.safe_find(pt, 'core:PersonTypeCode', namespaces) or self.safe_find(pt, 'a:PersonTypeCode', namespaces)) == 'EMP' for pt in person_types)

            
            accounts = self.parse_accounts(response_base, namespaces)

        
            member_info = {
                'persnbr': persnbr,
                'full_name': fullname,
                'firstname': firstname,
                'lastname': lastname,
                'adddate': self.safe_find(person_data, 'core:AddDate', namespaces) or self.safe_find(person_data, 'a:AddDate', namespaces),
                'age': age,
                'last_updated': last_updated,
                'is_active': (self.safe_find(person_data, 'core:MemberGroup', namespaces) or self.safe_find(person_data, 'a:MemberGroup', namespaces) or '').lower() == 'live',
                'is_deceased': is_deceased_raw == 'true' if is_deceased_raw is not None else None,
                'member_number': self.safe_find(person_data, 'core:MemberNumber', namespaces) or self.safe_find(person_data, 'a:MemberNumber', namespaces),
                'address': address_str or "N/A", # Provide default if None
                'city': city,
                'state': state,
                'zip_code': zip_code,
                'accounts': accounts, 
                'ssn': self.safe_find(person_data, 'core:TaxId', namespaces) or self.safe_find(person_data, 'a:TaxId', namespaces),
                'email': email or "N/A", 
                'mobile_phone': phone_number or "N/A", 
                'date_of_birth': date_birth,
                'is_employee': is_employee
            }

            self.logger.debug(f"Parsed is_deceased value: {member_info.get('is_deceased')}") # Use .get() for safety
            self.logger.debug(f"Parsed last_updated value: {member_info.get('last_updated')}")
            self.logger.info(f"Successfully parsed member info for person number: {member_info.get('persnbr')}")
            self.logger.debug(f"Parsed member info: {member_info}")
            return member_info

        except ET.ParseError as e:
            self.logger.error(f"Failed to parse member info XML response: {str(e)}")
            self.logger.debug(f"Problematic XML:\n{response_content.decode('utf-8', errors='ignore') if isinstance(response_content, bytes) else str(response_content)}")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing member info: {str(e)}", exc_info=True)
            return None

    def parse_accounts(self, response_base, namespaces): 
        """Parses account information from the DNA API response."""
        self.logger.debug("Parsing account information")
        accounts = []
        # Find Accounts element relative to the response_base (GetTaxIdDataResponse)
        # Try core: prefix first, then a:
        accounts_elem = response_base.find('core:Accounts', namespaces) or response_base.find('a:Accounts', namespaces)
        if accounts_elem is None:
            self.logger.warning("Could not find 'core:Accounts' or 'a:Accounts' element directly under GetTaxIdDataResponse.")
            # Log structure for debugging
            self.logger.debug(f"Structure of response_base when looking for Accounts:\n{self.prettify_xml(ET.tostring(response_base, encoding='unicode'))}")
            return [] # Return empty list if Accounts element is missing

        account_data_elements = accounts_elem.findall('core:AccountTaxIdData', namespaces) or accounts_elem.findall('a:AccountTaxIdData', namespaces)
        self.logger.info(f"Found {len(account_data_elements)} account data elements in response")

        for account_data in account_data_elements:
            account = {
                'account_number': self.safe_find(account_data, 'core:AccountNumber', namespaces) or self.safe_find(account_data, 'a:AccountNumber', namespaces),
                'account_type': self.safe_find(account_data, 'core:MajorAccountTypeCode', namespaces) or self.safe_find(account_data, 'a:MajorAccountTypeCode', namespaces),
                'product_code': self.safe_find(account_data, 'core:CurrentMinorAccountTypeCode', namespaces) or self.safe_find(account_data, 'a:CurrentMinorAccountTypeCode', namespaces),
                'balance': self.format_currency(self.safe_find(account_data, 'core:BalanceAmount', namespaces) or self.safe_find(account_data, 'a:BalanceAmount', namespaces)),
                'available_balance': self.format_currency(self.safe_find(account_data, 'core:AvailableBalance', namespaces) or self.safe_find(account_data, 'a:AvailableBalance', namespaces)),
                'date_opened': self.safe_find(account_data, 'core:DateAccountOpened', namespaces) or self.safe_find(account_data, 'a:DateAccountOpened', namespaces),
                'status': self.safe_find(account_data, 'core:CurrentAccountStatusCode', namespaces) or self.safe_find(account_data, 'a:CurrentAccountStatusCode', namespaces),
              
            }
            accounts.append(account)
        self.logger.info(f"Parsed {len(accounts)} accounts after processing")
        return accounts


    def format_currency(self, amount):
        try:
            return f"${float(amount):.2f}" if amount else "$0.00"
        except ValueError:
            return "$0.00"

    def calculate_age(self, date_birth):
        if not date_birth:
            return None
        try:
            birth_date = datetime.strptime(date_birth, "%Y-%m-%dT%H:%M:%S")
            today = datetime.now()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return age
        except ValueError:
            self.logger.error(f"Invalid date format for date_birth: {date_birth}")
            return None

    def get_financial_transactions(self, acctNbr, limit=10):
        self.logger.info(f"Retrieving financial transactions for account: {acctNbr}")
        try:
            if not self.ensure_authentication():
                self.logger.error(f"Authentication failed for account {acctNbr} transactions")
                return None # Authentication failed
        except Exception as auth_err:
            self.logger.warning(f"DNA authentication failed before getting transactions for account {acctNbr}: {auth_err}")
            return None

        if not self.application_id or not self.ntwk_node_name or not self.whois_response:
            self.logger.error("Missing required parameters for financial transactions request")
            # Raise error or return None? Returning None is safer for caller.
            # raise DNAApiError("Missing required parameters for financial transactions request")
            return None
        
        # Construct request body directly - ENSURE 7703 REQUEST TYPE IS USED
        request_body = f"""
            <RequestBase i:type="AccountTransactionHistoryRequest" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
              <MethodNumber>2</MethodNumber>
              <ReferenceNumber>{html.escape(str(acctNbr))}</ReferenceNumber>
              <RequestTypeCode>7703</RequestTypeCode>
              <AccountNumber>{html.escape(str(acctNbr))}</AccountNumber>
              <MaxReturnCount>{limit}</MaxReturnCount>
            </RequestBase>"""

        # Log the request body for debugging
        self.logger.debug(f"Transaction request body for account {acctNbr}:\n{request_body}")

        # Prepare full envelope using helper (Keep consistency)
        full_request_xml = self._prepare_submit_request_envelope(request_body)
        if full_request_xml is None:
            self.logger.warning(f"Failed to prepare request envelope for account transactions {acctNbr}")
            return None

        headers = {
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': '"http://www.opensolutions.com/CoreApi/ICoreApiService/SubmitRequest"'
        }
        
        self.logger.info(f"Making API call to fetch transactions for account {acctNbr}")
        try:
            response = self._make_request(self.dna_endpoint, headers, full_request_xml)
            if response is None:
                 self.logger.warning(f"API request failed when fetching transactions for account {acctNbr}")
                 return None
                 
            self.logger.info(f"Successfully received response for account {acctNbr} transactions")
            # Use the simpler parser from user feedback
            transactions = self.parse_financial_transactions(response.content)
            self.logger.info(f"Parsed {len(transactions) if transactions else 0} transactions for account {acctNbr}")
            return transactions
        except Exception as e:
            self.logger.error(f"Unexpected error getting transactions for account {acctNbr}: {str(e)}", exc_info=True)
            return None

    def parse_financial_transactions(self, response_content):
        # Simpler parser based on user feedback
        self.logger.debug("Parsing financial transactions from response (Simpler Logic)")
        try:
            # Ensure response_content is bytes for ET.fromstring
            if isinstance(response_content, str):
                response_content = response_content.encode('utf-8')

            root = ET.fromstring(response_content)
            self.logger.debug(f"Financial transactions response XML: {self.prettify_xml(ET.tostring(root, encoding='unicode'))}")

            # Check if the response was successful
            namespaces = {
                's': 'http://schemas.xmlsoap.org/soap/envelope/',
                'core': 'http://www.opensolutions.com/CoreApi',
                'a': 'http://schemas.datacontract.org/2004/07/OpenSolutions.CoreApiService.Services.Messages',
                'i': 'http://www.w3.org/2001/XMLSchema-instance'
            }
            
            # First check if the overall request was successful
            user_auth_elem = root.find('.//core:UserAuthentication', namespaces)
            if user_auth_elem is not None:
                overall_successful_elem = user_auth_elem.find('core:WasSuccessful', namespaces)
                if overall_successful_elem is None or overall_successful_elem.text.lower() != 'true':
                    self.logger.error("Overall API request failed (UserAuthentication WasSuccessful is not 'true').")
                    return None
            
            # Find the specific response for transaction history
            response_base = None
            for resp in root.findall('.//core:Responses/core:ResponseBase', namespaces):
                if resp.get('{' + namespaces['i'] + '}type') == 'AccountTransactionHistoryResponse':
                    response_base = resp
                    break
            
            if response_base is None:
                self.logger.error("Could not find AccountTransactionHistoryResponse in the response.")
                return None
            
            # Check if the specific response was successful
            specific_successful_elem = response_base.find('a:WasSuccessful', namespaces)
            if specific_successful_elem is not None and specific_successful_elem.text.lower() != 'true':
                self.logger.warning("AccountTransactionHistoryResponse WasSuccessful is not 'true'.")
                # Check for errors
                errors_elem = response_base.find('a:Errors', namespaces)
                if errors_elem is not None:
                    for error in errors_elem.findall('a:Error', namespaces):
                        err_msg = self.safe_find(error, 'a:ErrorMessage', namespaces)
                        if err_msg:
                            self.logger.error(f"Error in transaction response: {err_msg}")
                return None

            # Now find the transactions
            transactions = []
            # Use findall with './/' to search anywhere in the tree for 'a:Rtxn'
            rtxn_elements = response_base.findall('.//a:Rtxn', namespaces)
            if not rtxn_elements:
                # Try alternate paths if the expected path doesn't work
                rtxn_elements = root.findall('.//a:Rtxn', namespaces)
                
            self.logger.info(f"Found {len(rtxn_elements)} 'a:Rtxn' elements.")

            for transaction in rtxn_elements:
                act_date_time = self.safe_find(transaction, 'a:ActivityDateTime', namespaces)
                date, time = act_date_time.split('T') if act_date_time and 'T' in act_date_time else (act_date_time, None)

                amount = self.safe_find(transaction, 'a:TransactionAmount', namespaces)
                formatted_amount = "$0.00"
                if amount:
                    try:
                        amount_float = float(amount)
                        formatted_amount = f"${abs(amount_float):.2f}"
                        if amount_float < 0:
                            formatted_amount = f"-{formatted_amount}"
                    except ValueError:
                         self.logger.warning(f"Could not format transaction amount: {amount}")

                transaction_type = self.safe_find(transaction, 'a:RtxnTypeCode', namespaces)
                # Prioritize ExternalRtxnDescription if available
                description = self.safe_find(transaction, 'a:ExternalRtxnDescription', namespaces)
                if not description:
                    # Fallback to internal description or type code mapping
                    description = self.safe_find(transaction, 'a:RtxnDescription', namespaces)
                    if not description:
                         description = self.transaction_type_descriptions.get(transaction_type, f'Type: {transaction_type}')

                trans_data = {
                    'date': date,
                    'time': time.split('.')[0] if time else None, # Remove milliseconds
                    'amount': formatted_amount,
                    'transaction_type': transaction_type,
                    'description': description,
                    'source': self.safe_find(transaction, 'a:RtxnSourceCd', namespaces),
                }
                transactions.append(trans_data)

            self.logger.info(f"Parsed {len(transactions)} financial transactions")
            return transactions
        except ET.ParseError as e:
            self.logger.error(f"Failed to parse financial transactions XML: {str(e)}")
            # Log the problematic content if parsing fails
            self.logger.debug(f"Problematic XML:\n{response_content.decode('utf-8', errors='ignore')}")
            return None # Return None on parsing error
        except Exception as e:
            # Catch any other unexpected errors during parsing
            self.logger.error(f"Error parsing financial transactions: {str(e)}", exc_info=True)
            return None # Return None on other errors


    def get_member_info_by_member_number(self, member_number):
        """
        Fetches member information directly using Member Number (ReqTypCd 7725, Method 3).
        This method uses MethodNbr=3 which returns data for the specified member number.
        Returns None if the API call fails due to connection issues or if the member is not found.
        """
        self.logger.info(f"Attempting to fetch member info directly by member number: {member_number} using ReqTypCd 7725 / Method 3")
        try:
            if not self.ensure_authentication():
                return None # Authentication failed
        except Exception as auth_err:
            self.logger.warning(f"DNA authentication failed before getting member info for {member_number}: {auth_err}")
            return None

        # Construct the request body for GetTaxIdDataRequest (7725) using Member Number (Method 3)
        request_body = f"""
            <RequestBase i:type="GetTaxIdDataRequest" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
              <MethodNumber>3</MethodNumber>
              <ReferenceNumber>{html.escape(str(member_number))}</ReferenceNumber>
              <RequestTypeCode>7725</RequestTypeCode>
            </RequestBase>"""

        full_request_xml = self._prepare_submit_request_envelope(request_body)
        if full_request_xml is None:
            self.logger.warning(f"Failed to prepare request envelope for member number {member_number}")
            return None
            
        headers = {
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': '"http://www.opensolutions.com/CoreApi/ICoreApiService/SubmitRequest"'
        }

        try:
            response = self._make_request(self.dna_endpoint, headers, full_request_xml)
            if response is None:
                self.logger.warning(f"API request failed when fetching member info for member number {member_number}")
                return None

            self.logger.debug(f"Full XML response before parsing:\n{self.prettify_xml(response.content)}")
            return self.parse_member_info(response.content)
        except Exception as e:
            self.logger.error(f"Unexpected error getting member info for member {member_number}: {str(e)}", exc_info=True)
            return None
            
    def get_person_detail_by_member_number(self, member_number):
        """
        Fetches person details directly using Member Number (ReqTypCd 7711).
        This is a convenience method that returns member details without requiring a separate call.
        Returns None if the API call fails due to connection issues or if the person is not found.
        
        Note: This method is being replaced by get_member_info_by_member_number which uses Method 3
        to directly get member info by member number.
        """
        self.logger.info(f"Attempting to fetch person details directly by member number: {member_number}")
        try:
            # Use the new method that directly queries by member number
            return self.get_member_info_by_member_number(member_number)
        except Exception as e:
            self.logger.error(f"Unexpected error getting person details for member {member_number}: {str(e)}", exc_info=True)
            return None

    def safe_find(self, element, path, namespaces):
        """Safely find an element and return its text, handling None."""
        """Safely find an element and return its text, handling None. Adds logging."""
        if element is None:
            # self.logger.warning(f"safe_find called with None element for path: {path}") # Can be noisy
            return None
        found = element.find(path, namespaces)
        if found is None:
            # Log only if the element wasn't found using the specific path
            # self.logger.debug(f"safe_find: Element not found for path '{path}' within parent {element.tag}") # Can be noisy
            pass # Don't log every miss, as we try multiple namespaces now
        return found.text if found is not None else None
