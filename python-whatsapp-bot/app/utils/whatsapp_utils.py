import logging
from fastapi.responses import JSONResponse
import json
import requests
import os
from datetime import datetime
from openai import OpenAI
# from app.services.openai_service import generate_response
import re

from dotenv import load_dotenv, set_key, find_dotenv

#database
# from .database import insert_client , insert_srn , get_client_by_phone


from app.config import load_configurations
settings = load_configurations()

dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

# Replace the single data_history with a sessions dictionary
sessions = {}

# Zoho CRM Configuration
ZOHO_CRM_URL = "https://www.zohoapis.com/crm/v2"
ZOHO_ACCESS_TOKEN = os.getenv('ZOHO_ACCESS_TOKEN')

# Define cleanup function before using it
def cleanup_inactive_sessions(timeout_minutes=5):
    """Remove sessions that have been inactive for more than timeout_minutes"""
    current_time = datetime.now()
    inactive_sessions = []
    
    for phone_number, session in sessions.items():
        last_activity = datetime.fromisoformat(session['last_activity'])
        if (current_time - last_activity).total_seconds() > timeout_minutes * 60:
            inactive_sessions.append(phone_number)
    
    for phone_number in inactive_sessions:
        del sessions[phone_number]
        logging.info(f"Cleaned up inactive session for {phone_number}")

def send_scheduled_whatsapp_message():
    """Send a reminder message on the 10th of every month."""
    recipient = os.getenv("RECIPIENT_WAID")  # Fetch recipient from environment
    if not recipient:
        logging.error("❌ No recipient phone number found! Skipping reminder.")
        return

    text = "Reminder: Your scheduled task for the 10th is due today!"

    try:
        message_data = get_text_message_input(recipient, text)
        response_code = send_message(message_data)

        if response_code == 200:
            logging.info(f"✅ Reminder successfully sent to {recipient}")
        else:
            logging.error(f"❌ Failed to send reminder. Response Code: {response_code}")

    except Exception as e:
        logging.error(f"❌ Error sending reminder: {str(e)}")


# Initialize scheduler after defining the cleanup function 
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_inactive_sessions, 'interval', minutes=15)  # Remove the parentheses
scheduler.add_job(send_scheduled_whatsapp_message, 'cron', day=14, hour=22, minute=17, timezone="Asia/Kolkata")

scheduler.start()

def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    logging.info(f"Content-type: {response.headers.get('content-type')}")
    logging.info(f"Body: {response.text}")


def get_text_message_input(recipient, text):
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    )


client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

session = {}
def generate_response(body):
    phone_number = body['entry'][0]['changes'][0]['value']['contacts'][0]['wa_id']
    message_body = body['entry'][0]['changes'][0]['value']['messages'][0]['text']['body']
    # message_id = body['entry'][0]['changes'][0]['value']['messages'][0]['id']
    
    # Initialize session only if it doesn't exist for this phone number
    if phone_number not in session:
        session[phone_number] = {"data": {} , "conversation_history": [] }

    session[phone_number]["conversation_history"].append(f"User: {message_body}")

    # client_data = get_client_by_phone(phone_number)

    
    # Append the new message to existing conversation history

    print("--------------------------------conversation_history---------------------------------",session)

    
    travel_prompt = f""" 
    You are an AI assistant for SENA Travel Agency.
    Greet the user with a friendly introduction about who you are and your role in assisting with their travel needs.
    
    Guide the user step by step, ensuring a smooth and engaging conversation while tracking conversation history to ask the next relevant question.
    conversation history :  {session[phone_number]["conversation_history"]}
    **Conversation Flow:**
    
    **1. Trip palaning details Request**
    Good Day!, sir/madam,

        Thank you for reaching out to Sena Holidays! ✨  
        To tailor-make your trip, could you please provide the following information:

        - Destination:  
        - Date of Travel:  
        - Number of Nights:  
        - Number of Adults:  
        - Number of Children and their Ages:  
        - Hotel Options (3★, 4★, or 5★):  
        - Type of Package (Family trip, Honeymoon, or Friends):  
        - Other requirements:

        Thank you for your time and consideration.

        Best regards,  
        Sena Holidays
    **2. Service Selection**
    - Present a list of travel services in a numbered format in the chosen city (if you dont know make activities up - atleast)
    - Ask the user to select a service from the list.


    3. Collecting Basic Details in single response**
    - Greet the user and introduce yourself.
    - Ask for the following details in a well-structured format:
      - Their name
      - Contact number (validate for 10-digit mobile format)
      - Location they want to travel to
      - Number of members traveling
    
    **4. Confirmation & Brochure**
    - Once they provide their details and select a service, summarize the details and ask for confirmation: 
      **"Are these details correct?"**
      
    - If they provide confirmation for summary like [ok , yes , yes correct , correct , yep , yup etc..] respond with only a JSON output: 
      "service": "selected service", "location" : "location user asked" , "confirmation": true , members: "count"


    
    **Additional Rules:**
    - no templated responses, be as humanlike as possible. the customer shouldnt be able to figure out if you are a bot or a sales person.
    - return the response in proper format.
    - Ensure responses are concise and engaging.
    - Do not repeat information unnecessarily. 
    - Do not greet everytime.
    - If a format (e.g., phone number) is incorrect, ask them to correct it without showing the pattern.
    - Do not re-ask details after they have been collected.
    - Avoid hallucinations or assumptions.
    - Must - not ask confimation again and again , even user give confirmation
    - If the user says **"thank you"**, respond politely but do not continue the conversation unless they ask something else.
"""  

    
    print("********* convo new hsitory **********",session[phone_number]["conversation_history"])
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful chatbot."},
            {"role": "user", "content":travel_prompt }
        ]
    )

    bot_response = response.choices[0].message.content

    session[phone_number]["conversation_history"].append(f"Bot: {bot_response}")

    # Create or update Zoho CRM record
    if not update_zoho_contact(phone_number, message_body):
        create_zoho_lead(phone_number, message_body)

    return bot_response

def delete_uploaded_file(media_id,uploaded_time):

    print("------------------- delete_uploaded_file ------------------------")

    url = f"https://graph.facebook.com/{settings.VERSION}/{media_id}"
    
    headers = {
        "Authorization": f"Bearer {settings.ACCESS_TOKEN}"
    }

    response = requests.delete(url, headers=headers)

    deleted_time = datetime.now()
    total_deletion_time = deleted_time - uploaded_time

    print("---------------------- total_deletion_time -----------------------",total_deletion_time)

    if response.status_code == 200:
        print(f"--------------------- File{media_id} deleted from Meta Server.------------------------")
    else:
        print(f"-----------------------Failed to delete{media_id} file.----------------------------")



def send_message(data):
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {settings.ACCESS_TOKEN}",
    }

    url = f"https://graph.facebook.com/{settings.VERSION}/{settings.PHONE_NUMBER_ID}/messages"

    try:
        logging.info("------------------- sending response ---------- %s",data)
        response = requests.post(
            url, data=data, headers=headers, timeout=10
        )  # 10 seconds timeout as an example
        response.raise_for_status() 

        return response.status_code
        
    except requests.Timeout:
        logging.error("Timeout occurred while sending message")
        return JSONResponse(
            content={"status": "error", "message": "Request timed out"},
            status_code=408
        )
    except requests.RequestException as e:
        logging.error(f"Request failed due to: {e}")
        return JSONResponse(
            content={"status": "error", "message": "Failed to send message"},
            status_code=500
        )
    else:
        log_http_response(response)
        return JSONResponse(
            content={"status": "success", "message": "Message sent successfully"},
            status_code=response.status_code
        )


def process_text_for_whatsapp(text):
    # Remove brackets
    pattern = r"\【.*?\】"
    # Substitute the pattern with an empty string
    text = re.sub(pattern, "", text).strip()

    # Pattern to find double asterisks including the word(s) in between
    pattern = r"\*\*(.*?)\*\*"

    # Replacement pattern with single asterisks
    replacement = r"*\1*"

    # Substitute occurrences of the pattern with the replacement
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text


def get_document_message_input(recipient, media_id, caption="" , filename=""):
    print("--------------- Entered into get_document_message_input -------------------- ")
    return json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "document",
        "document": {
            "id": media_id,
            "caption": caption,
            "filename": filename
        }
    })

def send_document(phone_number, media_id, caption="",uploaded_time = None , filename=""):
    print("--------------- inside send_docuent function -------------------- ")
    data = get_document_message_input(phone_number, media_id, caption , filename)
    response_code = send_message(data)
    if response_code == 200 :
        delete_uploaded_file(media_id,uploaded_time)
        # insert_client(session[phone_number]['data'],phone_number)
    return response_code
       
            


def upload_doc_to_meta_cloud(document_path):
    print("-------------- Entered into upload_doc_to_meta_cloud function ----------------")

    headers = {
        "Authorization": f"Bearer {settings.ACCESS_TOKEN}"
    }
    url = f"https://graph.facebook.com/{settings.VERSION}/{settings.PHONE_NUMBER_ID}/media"

    # Determine the file type based on extension
    file_type = 'application/pdf'  # Since we're handling PDF files
    
    # Open file and send it to Meta API
    with open(document_path, 'rb') as file:
        files = {
            'file': ('document.pdf', file, file_type)
        }

        payload = {
            'messaging_product': 'whatsapp',
            'type': 'document'
        }    

        response = requests.post(url, files=files, data=payload, headers=headers)

        uploaded_time = datetime.now()

        if response.status_code == 200:
            media_id = response.json()['id']
            logging.info("File uploaded successfully. Media ID:%s", media_id)
            return media_id , uploaded_time
        else:
            logging.error("Failed to upload file:%s", response.text)
            return None , None


def get_audio_message_input(recipient, media_id):
    """Create audio message input format for WhatsApp API"""
    return json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "audio",
        "audio": {
            "id": media_id
        }
    })

def convert_text_to_speech(text):
    """Convert text to speech using OpenAI's TTS API"""
    try:
        speech_file_path = "temp_speech.mp3"
        response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",  # You can choose from: alloy, echo, fable, onyx, nova, shimmer
            input=text
        )
        
        # Save the audio file using the recommended streaming approach
        with open(speech_file_path, 'wb') as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
        return speech_file_path
    except Exception as e:
        logging.error(f"Error in text-to-speech conversion: {e}")
        return None

def upload_audio_to_meta_cloud(audio_path):
    """Upload audio file to Meta's cloud storage"""
    print("-------------- Uploading audio to Meta cloud ----------------")

    headers = {
        "Authorization": f"Bearer {settings.ACCESS_TOKEN}"
    }
    url = f"https://graph.facebook.com/{settings.VERSION}/{settings.PHONE_NUMBER_ID}/media"
    
    with open(audio_path, 'rb') as file:
        files = {
            'file': ('audio.mp3', file, 'audio/mpeg')
        }
        
        payload = {
            'messaging_product': 'whatsapp',
            'type': 'audio'
        }    

        response = requests.post(url, files=files, data=payload, headers=headers)
        uploaded_time = datetime.now()

        if response.status_code == 200:
            media_id = response.json()['id']
            logging.info("Audio uploaded successfully. Media ID: %s", media_id)
            return media_id, uploaded_time
        else:
            logging.error("Failed to upload audio: %s", response.text)
            return None, None

def send_audio_response(wa_id, text_response):
    """Convert text to speech and send as audio message"""
    try:
        # Convert text to speech
        audio_path = convert_text_to_speech(text_response)
        if not audio_path:
            return False

        # Upload audio to Meta cloud
        media_id, uploaded_time = upload_audio_to_meta_cloud(audio_path)
        if not media_id:
            return False

        # Send audio message
        data = get_audio_message_input(wa_id, media_id)
        response_code = send_message(data)
        
        # Clean up
        if os.path.exists(audio_path):
            os.remove(audio_path)
        
        if response_code == 200:
            delete_uploaded_file(media_id, uploaded_time)
            return True
            
        return False
    except Exception as e:
        logging.error(f"Error sending audio response: {e}")
        return False
    

def update_session_data(phone_number,response_dict):
    conversation_extract_prompt = f"""
                            Extract all user information from this conversation history into a structured format:
                            {session[phone_number]["conversation_history"]}
                            
                            Extract and return ONLY a JSON object with these fields:
                            {{
                                "name": "user's name from conversation",
                                "email": "user's email from conversation",
                                "aadhar_number" : :"user's aadhar from conversation"
                                "type": "Individual or Business from conversation",
                                "pan": "PAN if Individual",
                                "gstin": "GSTIN if Business",
                                "service": "{response_dict.get('service', '')}",
                                "service_specific_data": "{response_dict.get('sub_service','')}"
                            }}
                            """

    # Get structured data from conversation
    extract_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Extract user information into JSON format only."},
            {"role": "user", "content": conversation_extract_prompt}
        ]
    )

    # Process the extraction response
    extract_text = extract_response.choices[0].message.content
    print("extract_text\n",extract_text)

    json_match = re.search(r'\{.*\}', extract_text, re.DOTALL)
    print("json_match",json_match)
    if json_match:
        extracted_data = json.loads(json_match.group())
        print("extracted_json\n",extracted_data)
        # Update session data
        session[phone_number]["data"].update(extracted_data)
        print("Updated session data:\n\n", session)  

    # if not get_client_by_phone(phone_number) :
        
    #     insert_client(session[phone_number]['data'],phone_number)



def process_whatsapp_message(body):
    wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    phone_number = body['entry'][0]['changes'][0]['value']['contacts'][0]['wa_id']

    print("----------------------body---------------------",body)
    
    # Handle different message types
    if message.get("type") == "text":
        message_body = message["text"]["body"]
        response = generate_response(body)
    elif message.get("type") == "audio":
        audio_id = message["audio"]["id"]
        audio_url = get_media_url(audio_id)
        if audio_url:
            message_body = process_audio_to_text(audio_url)
            if message_body:
                body["entry"][0]["changes"][0]["value"]["messages"][0]["text"] = {"body": message_body}
                response = generate_response(body)
            else:
                response = "I'm having trouble processing your voice message right now. Could you please either try sending the voice message again or type your message? This will help ensure I understand your request correctly."
        else:
            response = "I'm unable to access the voice message at the moment. Please try sending your message as text instead."
    else:
        response = "I can only process text and voice messages. Please send your message in either format."

    # data = get_text_message_input(wa_id, response)
    # send_message(data)

    try:
        print("---------------------- bot response --------------",response)
        # Try to parse response as JSON
        json_match_1 = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match_1:
            response_dict = json.loads(json_match_1.group())   
        
            if isinstance(response_dict, dict) and "service" in response_dict and "confirmation" in response_dict:
                if response_dict["confirmation"]:
                    service_type = response_dict["service"]
                    document_path = r"D:\Sena Projects\Travel Agency WA\python-whatsapp-bot\app\utils\travel_broucher.pdf"
                    if document_path:
                        media_id, uploaded_time = upload_doc_to_meta_cloud(document_path)
                        if media_id:
                            filename = f"{response_dict['location']} {response_dict.get('service')} brochure"
                            send_document(wa_id, media_id, f"Here is your {response_dict['service']} {service_type} Broucher for {response_dict['members']} members", uploaded_time ,filename)
                        return
                
        else:
            # Send both text and audio response
            data = get_text_message_input(wa_id, response)
            send_message(data)
            send_audio_response(wa_id, response)
                

    except Exception as e:
        logging.error(f"Error processing message: {str(e)}")
        fallback_message = "Sorry, I encountered an error processing your request."
        data = get_text_message_input(wa_id, fallback_message)
        send_message(data)

    # try:
    #     print("----------------------bot response--------------",response)
    #     # Try to parse response as JSON
    #     json_match_1 = re.search(r'\{.*\}', response, re.DOTALL)
    #     if json_match_1:
    #         try:
    #             response_dict = json.loads(json_match_1.group())                
    #             if isinstance(response_dict, dict) and "service" in response_dict and "confirmation" in response_dict:
    #                 if response_dict['service'] == 'GST' and response_dict["confirmation"]:
    #                     service_type = response_dict["service"]
    #                     document_path = "C:\\Users\\SENA1\\Desktop\\Whatapp bot\\python-whatsapp-bot\\app\\utils\\copy_gst_returns_sample.pdf"
    #                     if document_path:
    #                         media_id, uploaded_time = upload_doc_to_meta_cloud(document_path)
    #                         if media_id:
    #                             uploaded_status=send_document(wa_id, media_id, f"Here is your {service_type} document", uploaded_time)
    #                             if uploaded_status == 200:
    #                                 update_session_data(phone_number,response_dict)
    #                                 session[phone_number]['data']['status'] = 'completed'
    #                                 insert_response=insert_srn(session[phone_number]['data'],phone_number)
    #                                 if insert_response == 201 :
    #                                     message="✅ SRN created successfully for the service : "+ response_dict['sub_service']
    #                                     data = get_text_message_input(wa_id,message)
    #                                     send_message(data)

    #                 else:
    #                     update_session_data(phone_number,response_dict)
    #                     insert_response=insert_srn(session[phone_number]['data'],phone_number) #default status pending
    #                     if insert_response == 201 :
    #                         message="✅ SRN created successfully for the service : "+ response_dict['sub_service']
    #                         data = get_text_message_input(wa_id,message)
    #                         send_message(data)
    #                         return
    #         except json.JSONDecodeError:
    #             pass 
            
    #     else:
    #         # Send both text and audio response
    #         data = get_text_message_input(wa_id, response)
    #         send_message(data)
    #         # send_audio_response(wa_id, response)
            
    # except Exception as e:
    #     logging.error(f"Error processing message: {str(e)}")
    #     fallback_message = "Sorry, I encountered an error processing your request."
    #     data = get_text_message_input(wa_id, fallback_message)
    #     send_message(data)

def get_media_url(media_id):
    """Get the URL for downloading media content"""
    headers = {
        "Authorization": f"Bearer {settings.ACCESS_TOKEN}"
    }
    
    url = f"https://graph.facebook.com/{settings.VERSION}/{media_id}"
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            media_data = response.json()
            print("media url: ", media_data.get("url"))
            return media_data.get("url")
    except Exception as e:
        logging.error(f"Error getting media URL: {e}")
    return None

def process_audio_to_text(audio_url):
    """Download and convert audio to text"""
    try:
        # Download the audio file
        headers = {
            "Authorization": f"Bearer {settings.ACCESS_TOKEN}"
        }
        audio_response = requests.get(audio_url, 
                                        headers=headers , 
                                        timeout=60,  # 30 seconds timeout
                                        verify=True )
        
        print("$$$$$$$$$$$$$ audio_response",audio_response)
        
        if audio_response.status_code == 200:
            # Save temporarily
            temp_file = f"temp_audio{datetime.now().timestamp()}.ogg" 
            
            try:
                with open(temp_file, "wb") as f:
                    f.write(audio_response.content)
            
            
                # Use OpenAI Whisper API for speech-to-text
                with open(temp_file, "rb") as audio_file:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        timeout=60
                    )
                    return transcript.text

            except Exception as whisper_error:
                        logging.error(f"Whisper API error: {whisper_error}")
                        return None 
            finally:
                # Clean up temporary file
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    
        else:
            logging.error(f"Failed to download audio. Status code: {audio_response.status_code}")
            return None

    except requests.Timeout:
        logging.error("Timeout while downloading audio file")
        return None
    except requests.ConnectionError:
        logging.error("Connection error while downloading audio file")
        return None
    except Exception as e:
        logging.error(f"Error processing audio: {str(e)}")
        return None

# def validate_phone_number(data):

#     # Replace these variables with your own values
#     access_token = settings.ACCESS_TOKEN
#     phone_number_id = settings.PHONE_NUMBER_ID
#     verification_method = 'SMS'  # or 'VOICE'
#     language_code = 'en_US'  # Language code for the verification message

#     # Step 1: Request a verification code
#     request_code_url = f'https://graph.facebook.com/v21.0/{phone_number_id}/request_code'
#     headers = {
#         'Authorization': f'Bearer {access_token}'
#     }
#     data = {
#         'code_method': verification_method,
#         'language': language_code
#     }

#     response = requests.post(request_code_url, headers=headers, data=data)
#     if response.status_code == 200:
#         print('Verification code sent successfully.')
#     else:
#         print(f'Failed to send verification code: {response.json()}')

#     # Step 2: Verify the code received by the user
#     verification_code = input('Enter the verification code received: ')
#     verify_code_url = f'https://graph.facebook.com/v21.0/{phone_number_id}/verify_code'
#     data = {
#         'code': verification_code
#     }

#     response = requests.post(verify_code_url, headers=headers, data=data)
#     if response.status_code == 200 and response.json().get('success'):
#         print('Phone number verified successfully.')
#         os.environ['is_Number_verified'] = True
#     else:
#         print(f'Failed to verify phone number: {response.json()}')



def is_valid_whatsapp_message(body):
    """
    Check if the incoming webhook event has a valid WhatsApp message structure.
    """
    # print("-------------------------------------------------------------------")
    # print("Entered ""is_valid_whatsapp_message"" ------body--> ",body)
    # print("-------------------------------------------------------------------")

    ph_no = body['entry'][0]['changes'][0]['value']['contacts'][0]['wa_id']

    os.environ['RECIPIENT_WAID'] = ph_no

    set_key(dotenv_path, 'RECIPIENT_WAID', ph_no)



    print("current user number",os.environ['RECIPIENT_WAID'])

    # validate_phone_number(body)



    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )

def is_session_expired(phone_number, timeout_minutes=30):
    if phone_number not in sessions:
        return True
    
    last_activity = datetime.fromisoformat(sessions[phone_number]['last_activity'])
    return (datetime.now() - last_activity).total_seconds() > timeout_minutes * 60

def create_zoho_lead(phone_number, message):
    """Create a lead in Zoho CRM from WhatsApp message"""
    try:
        headers = {
            "Authorization": f"Bearer {ZOHO_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        
        data = {
            "data": [{
                "Phone": phone_number,
                "Last_Name": f"WhatsApp User {phone_number}",
                "Description": f"WhatsApp Message: {message}",
                "Lead_Source": "WhatsApp"
            }]
        }
        
        response = requests.post(
            f"{ZOHO_CRM_URL}/Leads",
            headers=headers,
            json=data
        )
        
        if response.status_code == 201:
            logging.info(f"✅ Lead created in Zoho CRM for {phone_number}")
            return response.json()
        else:
            logging.error(f"❌ Failed to create lead in Zoho CRM: {response.text}")
            return None
            
    except Exception as e:
        logging.error(f"❌ Error creating Zoho CRM lead: {str(e)}")
        return None

def update_zoho_contact(phone_number, message):
    """Update contact in Zoho CRM with new WhatsApp message"""
    try:
        # First search for existing contact
        headers = {
            "Authorization": f"Bearer {ZOHO_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        
        search_response = requests.get(
            f"{ZOHO_CRM_URL}/Contacts/search",
            headers=headers,
            params={"criteria": f"(Phone:equals:{phone_number})"}
        )
        
        if search_response.status_code == 200:
            contacts = search_response.json().get('data', [])
            
            if contacts:
                contact_id = contacts[0]['id']
                # Update existing contact
                update_data = {
                    "data": [{
                        "Description": f"Latest WhatsApp Message: {message}"
                    }]
                }
                
                update_response = requests.put(
                    f"{ZOHO_CRM_URL}/Contacts/{contact_id}",
                    headers=headers,
                    json=update_data
                )
                
                if update_response.status_code == 200:
                    logging.info(f"✅ Updated contact in Zoho CRM for {phone_number}")
                    return True
                    
        return False
        
    except Exception as e:
        logging.error(f"❌ Error updating Zoho CRM contact: {str(e)}")
        return False
