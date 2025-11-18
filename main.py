import os
from datetime import datetime, timedelta
from typing import List, Optional, Literal, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr

from database import db, create_document, get_documents

# Twilio
from twilio.rest import Client as TwilioClient

# Google Calendar
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

app = FastAPI(title="Real Estate AI Voice Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- ENV / Config ----
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")  # e.g., https://<backend-url>
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_CALLER_ID = os.getenv("TWILIO_CALLER_ID")  # Verified/owned number like +1XXXXXXXXXX

def get_twilio_client() -> Optional[TwilioClient]:
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return None

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")  # e.g., primary or calendar email


def get_google_calendar_service():
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN and GOOGLE_CALENDAR_ID):
        return None
    creds = Credentials(
        None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
        ],
    )
    # Force refresh to obtain access token
    try:
        creds.refresh_request
    except Exception:
        pass
    return build("calendar", "v3", credentials=creds)


# ---- Utilities ----

def serialize_doc(doc: dict) -> dict:
    from datetime import datetime as dt
    out = {**doc}
    _id = out.get("_id")
    if _id is not None:
        out["id"] = str(_id)
        del out["_id"]
    for k, v in list(out.items()):
        if isinstance(v, dt):
            out[k] = v.isoformat()
    return out


def list_collection(name: str, limit: Optional[int] = None, filter_dict: Optional[dict] = None) -> List[dict]:
    items = get_documents(name, filter_dict or {}, limit)
    return [serialize_doc(i) for i in items]


# ---- Schemas (request models) ----
class LeadIn(BaseModel):
    full_name: str
    email: Optional[EmailStr] = None
    phone: str
    country: str = "USA"
    state: Optional[str] = None
    nri: bool = True
    source: Optional[str] = None
    interest_level: Optional[Literal["low", "medium", "high"]] = None
    notes: Optional[str] = None


class ScriptIn(BaseModel):
    title: str
    content: str
    language: str = "en-US"


class CampaignIn(BaseModel):
    name: str
    script_id: Optional[str] = None
    target_states: Optional[List[str]] = None
    nri_only: bool = True


class MeetingIn(BaseModel):
    lead_id: str
    senior_name: str
    meeting_time: datetime
    meeting_channel: Literal["zoom", "google_meet", "phone", "in_person"] = "zoom"
    location: Optional[str] = None
    notes: Optional[str] = None


# ---- Basic routes ----
@app.get("/")
def read_root():
    return {"message": "Real Estate AI Voice Agent API"}


@app.get("/api/hello")
def hello():
    return {"message": "Backend is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    response["twilio"] = "✅ Configured" if (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_CALLER_ID) else "❌ Not Configured"
    response["google_calendar"] = "✅ Configured" if (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN and GOOGLE_CALENDAR_ID) else "❌ Not Configured"
    response["public_base_url"] = PUBLIC_BASE_URL or "❌ Not Set (required for Twilio webhooks)"
    return response


# ---- Leads ----
@app.post("/api/leads")
def create_lead(lead: LeadIn):
    data = lead.model_dump()
    data["status"] = "new"
    lead_id = create_document("lead", data)
    return {"id": lead_id}


@app.get("/api/leads")
def get_leads(status: Optional[str] = None, limit: Optional[int] = 100):
    filt = {"status": status} if status else {}
    return list_collection("lead", limit, filt)


# ---- Scripts ----
@app.post("/api/scripts")
def create_script(script: ScriptIn):
    script_id = create_document("script", script)
    return {"id": script_id}


@app.get("/api/scripts")
def get_scripts(limit: Optional[int] = 50):
    return list_collection("script", limit)


# ---- Campaigns ----
@app.post("/api/campaigns")
def create_campaign(campaign: CampaignIn):
    data = campaign.model_dump()
    data["status"] = "draft"
    campaign_id = create_document("campaign", data)
    return {"id": campaign_id}


@app.get("/api/campaigns")
def get_campaigns(limit: Optional[int] = 50):
    return list_collection("campaign", limit)


@app.post("/api/campaigns/{campaign_id}/start")
def start_campaign(campaign_id: str):
    from bson import ObjectId
    if db is None:
        raise HTTPException(500, "Database not available")
    campaign = db["campaign"].find_one({"_id": ObjectId(campaign_id)})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    filt: dict[str, Any] = {}
    if campaign.get("nri_only", True):
        filt["nri"] = True
    states = campaign.get("target_states") or []
    if states:
        filt["state"] = {"$in": states}

    filt_status = {"status": {"$in": ["new", "no_answer", "callback_requested"]}}
    full_filter = {**filt, **filt_status}
    result = db["lead"].update_many(full_filter, {"$set": {"status": "queued", "updated_at": datetime.utcnow()}})

    db["campaign"].update_one({"_id": ObjectId(campaign_id)}, {"$set": {"status": "running", "updated_at": datetime.utcnow()}})

    return {"updated_leads": result.modified_count, "status": "running"}


@app.post("/api/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str):
    from bson import ObjectId
    if db is None:
        raise HTTPException(500, "Database not available")
    res = db["campaign"].update_one({"_id": ObjectId(campaign_id)}, {"$set": {"status": "paused", "updated_at": datetime.utcnow()}})
    if not res.matched_count:
        raise HTTPException(404, "Campaign not found")
    return {"status": "paused"}


# ---- Meetings ----
@app.post("/api/meetings")
def create_meeting(meeting: MeetingIn):
    meeting_id = create_document("meeting", meeting)
    return {"id": meeting_id}


@app.get("/api/meetings")
def get_meetings(limit: Optional[int] = 100):
    return list_collection("meeting", limit)


class GoogleMeetingIn(BaseModel):
    lead_id: str
    senior_name: str
    meeting_time: datetime
    duration_minutes: int = 30
    title: Optional[str] = None
    description: Optional[str] = None


@app.post("/api/meetings/google")
def create_google_meeting(payload: GoogleMeetingIn):
    from bson import ObjectId
    if db is None:
        raise HTTPException(500, "Database not available")
    lead = db["lead"].find_one({"_id": ObjectId(payload.lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")

    service = get_google_calendar_service()
    if service is None:
        raise HTTPException(400, "Google Calendar not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, GOOGLE_CALENDAR_ID.")

    start = payload.meeting_time
    end = start + timedelta(minutes=payload.duration_minutes)

    summary = payload.title or f"Consultation with {lead.get('full_name')}"
    description = payload.description or f"Lead: {lead.get('full_name')} | Phone: {lead.get('phone')} | Senior: {payload.senior_name}"

    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        "attendees": [
            {"email": lead.get("email")} if lead.get("email") else {}
        ],
        "conferenceData": {
            "createRequest": {"requestId": f"meet-{payload.lead_id}-{int(datetime.utcnow().timestamp())}"}
        },
    }

    created = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event, conferenceDataVersion=1).execute()

    meeting_doc = {
        "lead_id": payload.lead_id,
        "senior_name": payload.senior_name,
        "meeting_time": payload.meeting_time,
        "meeting_channel": "google_meet",
        "location": created.get("hangoutLink"),
        "notes": "Google Calendar event created",
        "google_event_id": created.get("id"),
        "google_meet_link": created.get("hangoutLink"),
    }
    meeting_id = create_document("meeting", meeting_doc)

    # Update lead status
    from bson import ObjectId as OID
    db["lead"].update_one({"_id": OID(payload.lead_id)}, {"$set": {"status": "meeting_scheduled", "updated_at": datetime.utcnow()}})

    return {
        "id": meeting_id,
        "google_event_id": created.get("id"),
        "google_meet_link": created.get("hangoutLink"),
    }


# ---- Call Simulation (legacy) ----
class CallSimIn(BaseModel):
    lead_id: str
    outcome: Literal["no_answer", "not_interested", "callback_requested", "interested"]
    callback_time: Optional[datetime] = None
    notes: Optional[str] = None


@app.post("/api/calls/simulate")
def simulate_call(payload: CallSimIn):
    from bson import ObjectId
    if db is None:
        raise HTTPException(500, "Database not available")

    lead_oid = ObjectId(payload.lead_id)
    lead = db["lead"].find_one({"_id": lead_oid})
    if not lead:
        raise HTTPException(404, "Lead not found")

    new_status = payload.outcome
    db["lead"].update_one({"_id": lead_oid}, {"$set": {"status": new_status, "notes": payload.notes, "updated_at": datetime.utcnow()}})

    created_meeting_id = None
    if payload.outcome == "interested":
        meeting_doc = {
            "lead_id": payload.lead_id,
            "senior_name": "TBD",
            "meeting_time": datetime.utcnow(),
            "meeting_channel": "phone",
            "notes": payload.notes or "Auto-created on positive interest"
        }
        created_meeting_id = create_document("meeting", meeting_doc)
        db["lead"].update_one({"_id": lead_oid}, {"$set": {"status": "meeting_scheduled"}})

    return {"lead_id": payload.lead_id, "status": new_status, "meeting_id": created_meeting_id}


# ---- Twilio Voice: Place call + TwiML ----
class PlaceCallIn(BaseModel):
    lead_id: str
    script_id: Optional[str] = None


@app.post("/api/calls/place")
def place_call(payload: PlaceCallIn):
    from bson import ObjectId
    if db is None:
        raise HTTPException(500, "Database not available")
    if not PUBLIC_BASE_URL:
        raise HTTPException(400, "PUBLIC_BASE_URL must be set for Twilio webhooks")

    twilio_client = get_twilio_client()
    if twilio_client is None or not TWILIO_CALLER_ID:
        raise HTTPException(400, "Twilio not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_CALLER_ID")

    lead = db["lead"].find_one({"_id": ObjectId(payload.lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")

    # Choose script: provided or latest
    script_text = ""
    if payload.script_id:
        s = db["script"].find_one({"_id": ObjectId(payload.script_id)})
        if s:
            script_text = s.get("content", "")
    else:
        s = db["script"].find_one(sort=[("created_at", -1)])
        if s:
            script_text = s.get("content", "")

    # Update lead status to calling
    db["lead"].update_one({"_id": ObjectId(payload.lead_id)}, {"$set": {"status": "calling", "updated_at": datetime.utcnow()}})

    # Twilio will fetch TwiML from our webhook
    from urllib.parse import urlencode
    params = urlencode({"lead_id": payload.lead_id, "script": script_text})
    twiml_url = f"{PUBLIC_BASE_URL}/twiml/voice?{params}"

    call = twilio_client.calls.create(
        to=lead.get("phone"),
        from_=TWILIO_CALLER_ID,
        url=twiml_url,
    )

    return {"call_sid": call.sid, "lead_id": payload.lead_id}


@app.get("/twiml/voice")
def twiml_voice(lead_id: str, script: Optional[str] = None):
    # Generate TwiML that reads the script and gathers input
    speak_text = script or "Hello. This is an outreach call."
    # Basic sanitization for XML
    def esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    instructions = "Press 1 to schedule a meeting. Press 2 to request a callback. Press 3 if not interested."
    twiml = f"""
        <Response>
            <Say voice=\"Polly.Amy\">{esc(speak_text)}</Say>
            <Pause length=\"1\"/>
            <Say>{esc(instructions)}</Say>
            <Gather input=\"dtmf\" numDigits=\"1\" action=\"/twiml/voice/handle?lead_id={esc(lead_id)}\" method=\"POST\" timeout=\"5\" />
            <Say>No input received. Thank you, goodbye.</Say>
            <Hangup/>
        </Response>
    """.strip()
    return Response(content=twiml, media_type="text/xml")


@app.post("/twiml/voice/handle")
async def twiml_voice_handle(request: Request, lead_id: str):
    form = await request.form()
    digit = form.get("Digits")
    from bson import ObjectId
    if db is None:
        return Response("<Response><Say>Server error.</Say></Response>", media_type="text/xml")

    status = "no_answer"
    note = None
    if digit == "1":
        status = "interested"
        note = "Pressed 1: interested"
        # Create meeting now (24h later) and try Google Calendar if configured
        meeting_time = datetime.utcnow() + timedelta(days=1)
        meeting_doc = {
            "lead_id": lead_id,
            "senior_name": "Auto-Assign",
            "meeting_time": meeting_time,
            "meeting_channel": "google_meet",
            "notes": "Auto-created from call input",
        }
        try:
            service = get_google_calendar_service()
            if service is not None and GOOGLE_CALENDAR_ID:
                event = {
                    "summary": "Consultation Call",
                    "description": note or "Auto-created",
                    "start": {"dateTime": meeting_time.isoformat(), "timeZone": "UTC"},
                    "end": {"dateTime": (meeting_time + timedelta(minutes=30)).isoformat(), "timeZone": "UTC"},
                    "conferenceData": {"createRequest": {"requestId": f"auto-{int(datetime.utcnow().timestamp())}"}},
                }
                created = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event, conferenceDataVersion=1).execute()
                meeting_doc["google_event_id"] = created.get("id")
                meeting_doc["google_meet_link"] = created.get("hangoutLink")
                meeting_doc["location"] = created.get("hangoutLink")
        except Exception:
            pass
        create_document("meeting", meeting_doc)
    elif digit == "2":
        status = "callback_requested"
        note = "Pressed 2: callback requested"
    elif digit == "3":
        status = "not_interested"
        note = "Pressed 3: not interested"
    else:
        status = "no_answer"
        note = "No input"

    try:
        db["lead"].update_one({"_id": ObjectId(lead_id)}, {"$set": {"status": status, "notes": note, "updated_at": datetime.utcnow()}})
    except Exception:
        pass

    # Respond TwiML
    message = {
        "interested": "Great! We have scheduled a consultation and sent details.",
        "callback_requested": "No problem. We will call you back soon.",
        "not_interested": "Understood. Thank you for your time.",
        "no_answer": "Thank you and goodbye.",
    }.get(status, "Thank you, goodbye.")

    twiml = f"<Response><Say>{message}</Say><Hangup/></Response>"
    return Response(content=twiml, media_type="text/xml")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
