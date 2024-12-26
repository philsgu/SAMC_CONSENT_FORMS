import streamlit as st
import re
from datetime import datetime, date, timedelta
from streamlit_drawable_canvas import st_canvas
from supabase import create_client, Client
import requests
import numpy as np
import PIL.Image as Image
import io
import os
import fitz # PYMuPDF
import base64
import uuid

today = date.today()
today_str = today.strftime("%m/%d/%Y")

# List of US States Abbreviations
STATES = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 
    'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 
    'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 
    'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 
    'NH', 'NJ', 'NM', 'NY', 'NC', 
    'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 
    'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 
    'VA', 'WA', 'WV', 'WI', 'WY'
]

# State abbreviation to full name mapping
STATE_NAMES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 
    'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia', 
    'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 
    'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 
    'ME': 'Maine', 'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan', 
    'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana', 
    'NE': 'Nebraska', 'NV': 'Nevada', 
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 
    'NY': 'New York', 'NC': 'North Carolina', 
    'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon', 
    'PA': 'Pennsylvania', 'RI': 'Rhode Island', 
    'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee', 
    'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont', 
    'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 
    'WI': 'Wisconsin', 'WY': 'Wyoming'
}

############# SUPABASE CONNECTION ###################
#Start Supabase Data Server Connection
@st.cache_resource
def init_supabase():
    """
    Initialize Supbase Client using Streamlit
    """
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SERVICE_ROW"]
    supbase: Client = create_client(url, key)
    return supbase

# get global file path 
path_context = {}
# UPLOAD PDF and DATA to Supbase
def upload_and_submit_to_supabase(submitted_data, force_upload=False):
    """
    Unified function to upload PDF and submit data to Supabase with duplicate prevention
        Args: submitted_data (dict): Dictionary containing all form submission data
        force_upload (bool): If True, bypasses duplicate check and forces upload

        Returns: tuple: (success_flag, message)
    """
    try:
        # Initialize Supabase client
        supabase = init_supabase()
        
        # Generate unique identifiers
        first_name = submitted_data.get('First Name', 'Unknown')
        last_name = submitted_data.get('Last Name', 'Unnamed')
        mrn = submitted_data.get('Medical Record Number', 'NoMRN')
        unique_id = str(uuid.uuid4())[:8]
        
        # Check for existing records to prevent duplicates
        existing_records = supabase.table("consentsamc_results").select("*").filter(
            "Medical Record Number", "eq", mrn
        ).execute()
        
        if existing_records.data and len(existing_records.data) > 0 and not force_upload:
            
            # can insert a popup with existing data of the contact person if matching data exist later
            #return False, f"Record for MRN {mrn} already exists"
            warning_message = f"""
                **This case has already been submitted by the following SAMC employee(s).  Please coordinate further.**
                Patient MRN: {mrn}
                Previous Submission:
                """
            # Helper function to get the submission date and type
            def get_submission_date_info(record):
                signature_date = record.get('Signature Date')
                verbal_auth_date = record.get('Verbal Auth Date')
                if signature_date:
                    return signature_date, "Signed"
                elif verbal_auth_date:
                    return verbal_auth_date, "Verbal"
                else:
                    return "Date not available", "Unknown"
            # Sort records by date by most recent
            sorted_records = sorted(
                existing_records.data,
                key=lambda x: (x.get('Signature Date') or x.get('Verbal Auth Date') or ''),
                reverse=True
            )
            
            # Add each sumission's details
            for i, record in enumerate(existing_records.data, 1):
                submission_date, auth_type = get_submission_date_info(record)
                warning_message += f"""
                Submission {i}:
                - Name: {record.get('Employee First Name', '')} {record.get('Employee Last Name', '')}
                - Dept: {record.get('Employee Department', '')}
                - Email: {record.get('Employee Email', '')}
                - Date Submitted: {submission_date}({auth_type} Authorization)
                """
            return True, warning_message, sorted_records
        
        # Generate PDF
        pdf_bytes = create_pdf(**submitted_data)
        
        if not pdf_bytes:
            return False, "Failed to generate PDF"
        
        # Create filename for PDF
        filename = f"{last_name}_{first_name}_{mrn}_{unique_id}.pdf"
        file_path = f"case_pdf_received/{filename}"
        path_context["file_path"] = file_path
        # Upload PDF to Supabase storage
        pdf_upload = supabase.storage.from_('completed_consent').upload(
            file=pdf_bytes,
            path=file_path,
            file_options={"content-type": "application/pdf"}
        )
        
        # Create a copy of submitted data without signature and PDF path
        database_data = submitted_data.copy()
        database_data.pop('Signature', None)  # Remove signature data
        
        # ADD the PDF file path to the database data
        database_data['pdf_file_path'] = file_path
            
        # Insert data into Supabase
        supabase.table("consentsamc_results").insert(database_data).execute()
    
        return True, "Data successfully submitted!", None
    
    except Exception as e:
        return False, f"Unexpected error: {e}", None

##### FUNCTION TO GET PDF URL FROM SUPABASE ######
def get_public_url():
    """
    Get the public URL for a file in Supabase storage.Args:
        supabase: Supabase client instance
        file_path: Path of the file in Supabase storage
    Returns:
        str: Public URL of the file"""
    supabase = init_supabase()
    try:
        # Get the public URL for the file
        public_url = supabase.storage.from_('completed_consent').get_public_url(path_context["file_path"])
        return public_url
    except Exception as e:
        st.error(f"Error getting PDF URL: {e}")
        return None
####################### VALIDATION FUNCTIONS #############################

# Name validation function
def validate_name(name, field_name="Name"):
    if not name:
        return False, f"{field_name} is required"
    
    if field_name == "Case Study Diagnosis":
        # Allow letters, numbers, spaces, hyphens, and periods
        # if not re.match(r'^[A-Za-z0-9\s.-]+$', name):
        #     return False, f"{field_name} should only contain letters, numbers, spaces, periods, and hyphens"
        if len(name) > 60:
            return False, f"{field_name} should be less than 60 characters long"
        return True, ""
    
    # Original validation for other name fields
    if not re.match(r'^[A-Za-z\s-]+$', name):
        return False, f"{field_name} should only contain letters, spaces, and hyphens"
    if len(name) < 2:
        return False, f"{field_name} should be at least 2 characters long"
    
    return True, ""

# Email validation function
def validate_email(email, field_name="Email"):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    samc_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@samc\.com$', re.IGNORECASE)
    if field_name == "Email":
        if not re.match(pattern, email):
            return False, f"Please enter a valid {field_name} address"
    else:
        if not re.match(samc_pattern, email):
            return False, f"Please enter a valid {field_name} address"
    
    return True, ""

# Phone number validation function
def validate_phone(phone):
    pattern = r'^\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})$'
    if not re.match(pattern, phone):
        return False, "Please enter a valid phone number"
    return True, ""

# Address validation function
def validate_address(address):
    if not address:
        return False, "Address is required"
    if len(address) < 5:
        return False, "Please enter a valid address"
    return True, ""

# City validation function
def validate_city(city):
    if not city:
        return False, "City is required"
    pattern_city = r'^[A-Za-z]+(?:[ -][A-Za-z]+)*$'
    if not re.match(pattern_city, city):
        return False, "City should only contain letters, spaces, and hyphens"
    return True, ""

# State validation function
def validate_state(state):
    if not state or state not in STATES:
        return False, "Please select a valid state"
    return True, ""

# Zip code validation function
def validate_zipcode(zipcode):
    pattern = r'^\d{5}(-\d{4})?$'
    if not re.match(pattern, zipcode):
        return False, "Please enter a valid 5-digit ZIP code (or 5+4 format)"
    return True, ""

# DOB validation function
def validate_dob(dob):
    if not dob:
        return False, "Date of Birth is required"
    return True, ""

# MRN validation function
def validate_mrn(mrn):
    if not mrn:
        return False, "Medical Record Number is required"
    if not mrn.isdigit():
        return False, "Medical Record Number should contain only numerical values"
    return True, ""

# Signature validation function
def validate_signature(canvas_result, verbal_authorization):

    if verbal_authorization:
        return True, ""
    
      # If not verbally authorized, perform standard signature validation
    if canvas_result is None:
        return False, "Signature is required"
    
    # Check if canvas is empty or no drawing was made
    if canvas_result.image_data is None:
        return False, "Signature is required"
    
    # Convert canvas data to a PIL Image to check if it's truly drawn on
    img = Image.fromarray(canvas_result.image_data)
    
    # Convert image to numpy array and check if any non-transparent pixels exist
    img_array = np.array(img)
    
    # Check if there are any non-transparent pixels 
    # (assuming alpha channel is the 4th channel in RGBA)
    if img_array.shape[2] == 4:  # RGBA image
        # Check if any pixel has opacity > 0
        if np.max(img_array[:,:,3]) == 0:
            return False, "Please provide a signature"
    
    return True, ""
# Use session state to pass data into PDF with collected image

def create_pdf(**kwargs):
    """
    Generate a PDF with embedded form data based on the case study consent template
    Args: **kwargs: Dictionary of form data to be embedded into the PDF
    Returns: bytes: PDF document with embedded data
    """
    # Load the original PDF template
    try:
        doc = fitz.open("case_study_consent.pdf")
    except Exception as e:
        st.error(f"Error opening PDF template: {e}")
        return None

    # First page of the document
    page = doc[0]

    # Define text insertion parameters 
    font_size = 10
    text_color = (0, 0, 0)  # Black color
    
    # Mapping of form fields to PDF coordinates
    field_positions = {
        "Patient Name": (118, 240),
        "DOB": (450, 240),
        "Address": (95, 258),
        "City": (300, 258),
        "State": (435, 258),
        "Zip Code": (495, 258),
        "Email": (90, 275),
        "Phone": (355, 275),
        "Diagnosis Focus": (140, 400),
        "Signature Date": (300, 615),
        "Authorized Person": (70, 650),
        "Verbal Authorization": (200, 685),
        "Verbal Auth Date": (265, 685),
    }

    # Insert collected data into appropriate locations
    for field, position in field_positions.items():
        value = ""
        if field == "Patient Name":
            value = f"{kwargs.get('First Name', '')} {kwargs.get('Last Name', '')}".strip()
        elif field == "DOB":
            value = kwargs.get('Date of Birth', '')
        elif field == "Address":
            value = kwargs.get('Address', '')
        elif field == "City":
            value = kwargs.get('City', '')
        elif field == "State":
            value = kwargs.get('State', '')
        elif field == "Zip Code":
            value = kwargs.get('ZIP Code', '')
        elif field == "Email":
            value = kwargs.get('Email', '')
        elif field == "Phone":
            value = kwargs.get('Phone', '')
        elif field == "Diagnosis Focus":
            value = kwargs.get('Case Study Diagnosis', '')
        elif field == "Signature Date":
            value = kwargs.get('Signature Date', '')
        elif field == "Authorized Person":
            value = kwargs.get('Authorized Person', '')
        elif field == "Verbal Authorization":
            value = kwargs.get('Verbal Authorization', '')
        elif field == "Verbal Auth Date":
            value = kwargs.get('Verbal Auth Date', '')

        # Insert text at specified position
        page.insert_text(position, value, fontsize=font_size, color=text_color)

    # Add signature
    signature = kwargs.get('Signature')
    if signature is not None and not isinstance(signature, str):
        try:
            # Convert numpy array to PIL Image
            from PIL import Image
            sig_img = Image.fromarray(signature)
            
            # Convert image to bytes
            img_byte_arr = io.BytesIO()
            sig_img.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()

            # Add signature to PDF
            sig_rect = fitz.Rect(70, 600, 225, 630)  # Adjust rectangle as needed
            page.insert_image(sig_rect, stream=img_byte_arr)
        except Exception as e:
            st.warning(f"Could not add signature: {e}")

    # Add verbal authorization details
    # verbal_auth = "Yes" if kwargs.get('Verbal Authorization', False) else ""
    # verbal_auth_date = kwargs.get('Verbal Authorization Date', '') if kwargs.get('Verbal Authorization', False) else ''# Using today's date if not specified
    
    # Construct employee name for verbal authorization
    employee_name = f"{kwargs.get('Employee First Name', '')} {kwargs.get('Employee Last Name', '')}".strip()
    
    # Insert verbal authorization details
    # page.insert_text((200, 685), f"{verbal_auth}", fontsize=font_size, color=text_color)
    # page.insert_text((260, 685), f"{verbal_auth_date}", fontsize=font_size, color=text_color)
    page.insert_text((360, 720), f"{employee_name}", fontsize=font_size, color=text_color)

    # Save the modified PDF to a bytes buffer
    pdf_bytes = doc.write()
    doc.close()

    return pdf_bytes

def display_pdf_download():
    """
    Create download button link using Supabase public URL
    Args:
    submitted_data:  Dict containing form submission data
    """
    try:
   

        # Get the public URL for the PDF file
        file_path = get_public_url()
        if not file_path:
            st.error("PDF file path not found in submission data.")
            return

        # Get the public URL for the PDF file
        else:
            st.link_button("View Completed Form", file_path)
                
    except Exception as e:
        st.error(f"Error getting PDF URL: {e}")
  
##### NTFY notification function ####
def send_ntfy_mssg(**kwargs):
    """
    Send notification to ntfy.sh channel about new case study consent form submission
    
    Args:
        **kwargs: Dictionary containing form submission data including:
            - Employee First Name
            - Employee Last Name
            - Employee Email
            - Case Study Diagnosis
            - Signature Date or Verbal Auth Date
    """
    # Get employee details
    employee_name = f"{kwargs.get('Employee First Name', '')} {kwargs.get('Employee Last Name', '')}"
    employee_email = kwargs.get('Employee Email', '')
    diagnosis = kwargs.get('Case Study Diagnosis', '')
    
    # Get submission date (either signature date or verbal auth date)
    submission_date = kwargs.get('Signature Date') or kwargs.get('Verbal Auth Date') or today_str
    
    # Create message
    message = (
        f"Date: {submission_date}\n"
        f"Employee: {employee_name}\n"
        f"Email: {employee_email}\n"
        f"Topic: {diagnosis}"
    )
    
    # Send notification
    response = requests.post(
        "https://ntfy.sh/gmeconsent",
        data=message,
        headers={
            "Title": "Case Consent Form Submission",
            "Priority": "urgent",
        },
    )


######### MAIN FUNCTION ##########
def main():
    st.subheader("AUTHORIZATION FOR MEDICAL CASE STUDY AND PUBLICATION OF DE-IDENTIFIED MEDICAL INFORMATION")
    st.markdown("""
                ## Purpose of Authorization
                Patient authorization is generally not required for case studies, as they typically use de-identified health information. However, some medical journals now require some form of authorization from the patient. This authorization may be necessary when the journal mandates that the author obtain the patient’s permission to use their information in the case study.

                It is important to note that this authorization cannot be used if the diagnosis is such that it could reasonably identify the patient, such as in the case of a rare disease. Depending on the publisher’s requirements, authorization may be obtained either by having the patient sign this document or through verbal consent.

                **Important Note:** Form submission is required to generate PDF document file for download.  All submitted data will be stored in HIPAA-compliant database. For technical support, please contact phillip.kim@samc.com.
                """)
    # Add a reset button
    if st.button("Reset Form"):
        # List of all form field keys
        form_keys = [
            'first_name', 'last_name', 'dob', 'mrn', 'email', 'phone',
            'address', 'city', 'state', 'zipcode', 'verbal_authorization',
            'authorized_person', 'employee_first_name',
            'employee_last_name', 'employee_email', 'employee_department',
            'case_study_diagnosis', 'submitted', 'submitted_data',
            'proceed_clicked', 'success_message'
        ]
        
        # Clear each key individually
        for key in form_keys:
            if key in st.session_state:
                del st.session_state[key]
        
        st.rerun()

    # Initialize session state if not exists
    if 'submitted' not in st.session_state:
        st.session_state.submitted = False
    if 'submitted_data' not in st.session_state:
        st.session_state.submitted_data = None
    if 'proceed_clicked' not in st.session_state:
        st.session_state.proceed_clicked = False
    if 'success_message' not in st.session_state:
        st.session_state.success_message = False
    
    # Function to clear form fields
    def clear_form():
        form_keys = [
            'first_name', 'last_name', 'dob', 'mrn', 'email', 'phone',
            'address', 'city', 'state', 'zipcode', 'verbal_authorization',
            'authorized_person', 'employee_first_name',
            'employee_last_name', 'employee_email', 'employee_department',
            'case_study_diagnosis', 'submitted', 'submitted_data',
            'proceed_clicked'
        ]
        
        for key in form_keys:
            if key in st.session_state:
                if key == 'dob':
                    st.session_state[key] = None
                elif key == 'state':
                    st.session_state[key] = ''
                elif key in ['verbal_authorization', 'submitted', 'proceed_clicked']:
                    st.session_state[key] = False
                else:
                    st.session_state[key] = ''
    
    # Display success message if needed
    if st.session_state.success_message:
        st.success("Form submitted successfully!")
        clear_form()
        st.session_state.success_message = False
        st.rerun()

    # Check if we have submitted data to process
    if st.session_state.submitted_data and not st.session_state.proceed_clicked:
        success, message, existing_data = upload_and_submit_to_supabase(st.session_state.submitted_data)
        
        if existing_data:
            # Display warning with multiple submissions
            st.warning(message)
            num_submissions = len(existing_data) if isinstance(existing_data, list) else 1
            st.info(f"Found {num_submissions} previous submission(s) with this MRN.")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Proceed Submission ANYWAY"):
                    st.session_state.proceed_clicked = True
                    success, message, _ = upload_and_submit_to_supabase(st.session_state.submitted_data, force_upload=True)
                    if success:
                        pdf_bytes = create_pdf(**st.session_state.submitted_data)
                        if pdf_bytes:
                            st.success("Form submitted successfully!")
                            display_pdf_download()
                            send_ntfy_mssg(**st.session_state.submitted_data)
                           
                        st.session_state.success_message = True
                        st.session_state.submitted_data = None
                        clear_form()
                        #st.rerun()
            with col2:
                if st.button("Cancel Submission"):
                    clear_form()
                    st.rerun()
        else:
           # No duplicates found, use the result from the initial upload attempt
            if success:  # Use the result from the first upload attempt
                pdf_bytes = create_pdf(**st.session_state.submitted_data)
                if pdf_bytes:
                    st.success("Form submitted successfully!")
                    display_pdf_download()
                    send_ntfy_mssg(**st.session_state.submitted_data)
                    
                st.session_state.success_message = True
                st.session_state.submitted_data = None
                clear_form()
    
######### START FORM FIELDS ##################     
    with st.form("validation_form"):
        # Patient Information
        st.header("Patient Information")

        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input(
                "First Name*", 
                key='first_name',
                placeholder='Enter first name'
            )
        with col2:
            last_name = st.text_input(
                "Last Name*", 
                key='last_name',
                placeholder='Enter last name'
            )
        
        col1, col2 = st.columns(2)
        with col1:
            dob = st.date_input(
                "Date of Birth*", 
                key='dob',
                min_value=datetime(1904, 1, 1),
                max_value=date.today(),
                format="MM/DD/YYYY",
                value=None
            )
        with col2:
            mrn = st.text_input(
                "Medical Record Number*", 
                key='mrn',
                placeholder='Enter MRN (numerical values only)'
            )
   
        email = st.text_input(
            "Email*", 
            key='email',
            placeholder='Enter email'
        )

        phone = st.text_input(
            "Cell Phone Number*", 
            key='phone',
            placeholder='Enter Cell Phone Number'
        )   

        col1, col2 = st.columns(2)
        with col1:
            address = st.text_input(
            "Address*", 
            key='address',
            placeholder='Enter full address'
            )
            state = st.selectbox(
                "State*", 
                options=[''] + STATES,
                key='state',
                format_func=lambda x: STATE_NAMES.get(x, x)  # Display full state name
            )
           
        with col2:
            city = st.text_input(
                "City*", 
                key='city',
                placeholder='Enter city'
            )
            zipcode = st.text_input(
                "ZIP Code*", 
                key='zipcode',
                placeholder='Enter ZIP code'
            )
         # Verbal Consent
        verbal_authorization = st.checkbox(
            "Verbal Authorization Obtained", 
            value=False,
            key='verbal_authorization',
        )
        st.text("Please sign below (Patient/Representative Signature)*")
        # EMBEDD SIGNATURE CANVAS
        canvas_result = st_canvas(
            fill_color="rgba(255, 165, 0, 0.3)",  # Fixed fill color with some opacity
            stroke_width=2,
            stroke_color="#000000",
            background_color="#00000000",  # Transparent background color
            update_streamlit=True,
            height=150,
            drawing_mode="freedraw",
            point_display_radius=1,
            key="canvas",
            )

        # Authorized Person Information
        auth_person = st.text_input(
            "Authorized Person Name and Relationship", 
            key='authorized_person',
            placeholder='Enter name and relationship'
        )     
               
        # SUBMITTER INFORMATION
        st.header("SAMC Authorized Information")
        col1, col2 = st.columns(2)
        with col1:
            employee_first_name = st.text_input(
                "Employee First Name*", 
                key='employee_first_name',
                placeholder='Enter first name'
            )
        with col2:
            employee_last_name = st.text_input(
                "Employee Last Name*", 
                key='employee_last_name',
                placeholder='Enter last name'
        ) 
        
        employee_email = st.text_input(
            "Employee SAMC Email*", 
            key='employee_email',
            placeholder='Enter email'
        )
        employee_department = st.text_input(
            "Employee Department*", 
            key='employee_department',
            placeholder='Enter department'
        )
        case_study_diagnosis = st.text_input(
            "Case Study Diagnosis*", 
            key='case_study_diagnosis',
            placeholder='Enter case study diagnosis'
        )

        ### SUBMIT HANDLER BUTTON ####
        submitted = st.form_submit_button("Submit")
        if submitted:
            # form validation
            validations = [
                validate_name(first_name, "First Name"),
                validate_name(last_name, "Last Name"),
                validate_dob(dob),
                validate_mrn(mrn),
                validate_email(email),
                validate_phone(phone),
                validate_address(address),
                validate_state(state),
                validate_city(city),
                validate_zipcode(zipcode),
               
                # Employee Information
                validate_name(employee_first_name, "Employee First Name"),
                validate_name(employee_last_name, "Employee Last Name"),
                validate_email(employee_email, "Employee SAMC Email"),
                validate_name(employee_department, "Employee Department"),
                validate_name(case_study_diagnosis, "Case Study Diagnosis"),
            ]
            #validate signatured based on verbal authorization status
            validations.append(validate_signature(canvas_result, verbal_authorization))
            if all(v[0] for v in validations):
                # Prepare submitted data
                submitted_data = {
                    "First Name": first_name,
                    "Last Name": last_name,
                    "Email": email,
                    "Phone": phone,
                    "Medical Record Number": mrn,
                    "Date of Birth": dob.strftime("%m/%d/%Y"),
                    "Address": address,
                    "City": city,
                    "State": state,
                    "ZIP Code": zipcode,
                    "Authorized Person": auth_person,
                    "Verbal Authorization": "Yes" if verbal_authorization else None,  # Convert to "Yes" or "No" based on verbal_authorization
                    # Handling signature for both verbal and non-verbal authorization
                    "Verbal Auth Date": today_str if verbal_authorization else None,
            
                    "Signature": ("Verbal Authorization" if verbal_authorization else (canvas_result.image_data if canvas_result and not verbal_authorization else None)),
                    "Signature Date": None if verbal_authorization else today_str,

                    "Employee First Name": employee_first_name,
                    "Employee Last Name": employee_last_name,
                    "Employee Email": employee_email,
                    "Employee Department": employee_department,
                    "Case Study Diagnosis": case_study_diagnosis,
                }
                    
                
                 # Only set the session state - don't upload to Supabase here
                st.session_state.submitted = True
                st.session_state.submitted_data = submitted_data
                st.session_state.proceed_clicked = False
                
                # Rerun to show the confirmation/duplicate check
                st.rerun()

            else:
                # Display validation errors
                for valid, message in validations:
                    if not valid:
                        st.error(message)

# Run the main function
if __name__ == "__main__":
    main()
