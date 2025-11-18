"""
Database Schemas for Real Estate Voice Agent

Each Pydantic model represents a MongoDB collection (collection name is the lowercase class name).
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime

class Lead(BaseModel):
    full_name: str = Field(..., description="Lead full name")
    email: Optional[EmailStr] = Field(None, description="Email address")
    phone: str = Field(..., description="E.164 formatted phone number")
    country: str = Field("USA", description="Country of residence")
    state: Optional[str] = Field(None, description="US state if applicable")
    nri: bool = Field(True, description="Is Non-Resident Indian")
    source: Optional[str] = Field(None, description="Lead source, e.g., csv, referral")
    interest_level: Optional[Literal["low", "medium", "high"]] = Field(None, description="Self-reported interest level")
    status: Literal["new", "queued", "calling", "no_answer", "not_interested", "callback_requested", "interested", "meeting_scheduled", "converted"] = Field("new")
    notes: Optional[str] = None

class Script(BaseModel):
    title: str = Field(..., description="Script title")
    content: str = Field(..., description="Call script content")
    language: str = Field("en-US", description="Voice language/locale")

class Campaign(BaseModel):
    name: str
    script_id: Optional[str] = Field(None, description="Reference to script document _id")
    target_states: Optional[List[str]] = Field(None, description="Filter by US states")
    nri_only: bool = Field(True)
    status: Literal["draft", "running", "paused", "completed"] = Field("draft")

class Meeting(BaseModel):
    lead_id: str
    senior_name: str
    meeting_time: datetime
    meeting_channel: Literal["zoom", "google_meet", "phone", "in_person"] = "zoom"
    location: Optional[str] = Field(None, description="Location if in_person")
    notes: Optional[str] = None
