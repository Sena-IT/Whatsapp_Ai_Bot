from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class LeadData(BaseModel):
    name: str
    email: str
    travel_location: str
    travel_date: str
    no_of_days: int
    no_of_persons: int
    whatsapp: str
    tour_type: str
    source: str

class ZohoLeadData(BaseModel):
    name: str
    email: str
    travel_location: str
    travel_date: str
    no_of_days: int
    no_of_persons: int
    whatsapp: str
    tour_type: str
    source: str

class FacebookLead(BaseModel):
    name: str
    email: str
    travel_location: str
    travel_date: str
    no_of_days: int
    no_of_persons: int
    whatsapp: str
    tour_type: str
    source: str = "Facebook Ad"

class GoogleLeadData(LeadData):
    source: str

class LeadResponse(BaseModel):
    status: str
    message: str
    lead_id: int
    text_file: str
    data: dict

class HealthResponse(BaseModel):
    status: str
    database: str