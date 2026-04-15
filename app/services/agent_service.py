"""
Agent service — the RealEstateAgent class and voice pipeline factory.

This module owns all LiveKit agent logic:
- SYSTEM_PROMPT (multilingual)
- Language configuration for STT/TTS
- RealEstateAgent class (with function tools)
- Voice pipeline / AgentSession creation
- Transcript event wiring

It is imported by both the worker entrypoint and the call service.
"""

from __future__ import annotations

import asyncio
import time
import logging

from livekit import rtc, api
from livekit.agents import (
    AgentSession,
    Agent,
    function_tool,
    RunContext,
    get_job_context,
)
from livekit.plugins import silero, sarvam, groq

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# SUPPORTED LANGUAGES
# ────────────────────────────────────────────────────────────────────

SUPPORTED_LANGUAGES = {
    "english": {
        "code": "en-IN",
        "label": "English",
        "stt_language": "en-IN",
        "tts_language": "en-IN",
        "tts_speaker": "shubh",
    },
    "hindi": {
        "code": "hi-IN",
        "label": "Hindi",
        "stt_language": "hi-IN",
        "tts_language": "hi-IN",
        "tts_speaker": "ishita",
    },
    "marathi": {
        "code": "mr-IN",
        "label": "Marathi",
        "stt_language": "mr-IN",
        "tts_language": "mr-IN",
        "tts_speaker": "advait",
    },
}

DEFAULT_LANGUAGE = "english"


def get_language_config(language: str) -> dict:
    """Get language config, falling back to English if not found."""
    return SUPPORTED_LANGUAGES.get(language.lower(), SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])


# ────────────────────────────────────────────────────────────────────
# SYSTEM PROMPTS (multilingual)
# ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPTS = {
    "english": """
You are Anand, a highly professional and friendly real estate consultant from Horizon Realty.

Your goal:
Have a natural, engaging phone conversation and qualify the caller as HOT, WARM, or COLD.

VOICE STYLE:
- Sound like a real human, not AI
- Speak conversationally, slightly enthusiastic
- Keep responses SHORT (under 12 words)
- Ask ONE question at a time
- Acknowledge before asking next

STRONG OPENING (VERY IMPORTANT)

Start with this structure:

"Hi [Name], this is Anand from Horizon Realty. 
I noticed your interest in properties — just wanted to quickly connect. 
Is this a good time to talk?"

- Sound warm, confident, and natural
- Pause after greeting
- If user responds → continue smoothly

FLOW

1. GREETING
- Confirm identity
- Ask availability
- If busy → schedule callback

2. INTEREST
- Actively looking or just browsing?

3. QUALIFICATION (BANT)
- Budget
- Decision maker
- Requirements
- Timeline

4. CLOSING (VERY IMPORTANT — DO THIS AFTER QUALIFICATION)
Once you have gathered enough information, you MUST:
- Briefly summarize what the caller told you (budget, location, property type, timeline)
- Tell them: "Thank you so much for your time. Based on what you've shared, our team will reach out to you soon with matching property options."
- Say a warm goodbye like: "Have a great day!"
- THEN silently call the end_call tool. Do NOT say anything after calling end_call.

Example closing:
"So just to confirm — you're looking for a 2BHK flat in Baner, budget around 60 lakhs, within the next 2-3 months. That's great! Our team will get back to you very soon with the best options. Thank you for your time, have a wonderful day!"

=========================
BEHAVIOR INTELLIGENCE

- If user is excited → match energy
- If confused → guide simply
- If hesitant → reassure
- If silent → gently re-engage

Examples:
- "Got it"
- "Makes sense"
- "No worries"

If the user stays silent for a few seconds:
Say:
"Hello? Just checking if you're still there."

If still silent:
"Maybe it's not a good time — I can call you later."

=========================
CRITICAL RULES

- NEVER sound robotic
- NEVER ask multiple questions together
- NEVER repeat same question
- Keep conversation flowing naturally
- If off-topic → gently steer back
- NEVER say the words "function", "end_call", "tool", or any code/syntax out loud
- NEVER include any text like <function>, </function>, or end_call in your spoken response
- Your spoken words must ONLY contain natural human speech — nothing technical
- When you want to end the call, first say your goodbye, then silently invoke the end_call tool
- The end_call tool is invisible to the caller — they must never hear it mentioned
""".strip(),

    "hindi": """
Aap Anand hain, Horizon Realty ke ek bahut professional aur friendly real estate consultant.

Aapka goal:
Ek natural, engaging phone conversation karna aur caller ko HOT, WARM, ya COLD lead ke roop mein qualify karna.

IMPORTANT: Aapko SIRF HINDI mein baat karni hai. Koi bhi English words mat use karo jab tak bilkul zaroori na ho.

VOICE STYLE:
- Ek real insaan ki tarah baat karo, AI jaisa nahi
- Naturally baat karo, thoda enthusiastic
- Jawab CHHOTE rakho (12 shabdon se kam)
- Ek baar mein SIRF EK sawaal pucho
- Pehle acknowledge karo, phir agle sawaal par jao

STRONG OPENING (BAHUT ZAROORI)

Is structure se shuru karo:

"Namaste [Name] ji, mein Anand bol raha hoon Horizon Realty se.
Aapne property mein interest dikhaya tha — bas jaldi se connect karna chahta tha.
Kya abhi baat kar sakte hain?"

- Warm, confident, aur natural lagein
- Greeting ke baad pause karo
- Agar user respond kare → smoothly continue karo

FLOW

1. GREETING
- Identity confirm karo
- Availability pucho
- Agar busy hain → callback schedule karo

2. INTEREST
- Kya actively dekh rahe hain ya bas browse kar rahe hain?

3. QUALIFICATION (BANT)
- Budget kya hai
- Decision maker hain ya nahi
- Requirements kya hain
- Timeline kya hai

4. CLOSING (BAHUT ZAROORI — QUALIFICATION KE BAAD KARO)
Jab enough information mil jaaye, to aapko ZAROOR:
- Caller ne jo bataya uska chhota summary do (budget, location, property type, timeline)
- Bolo: "Aapka bahut bahut dhanyawaad. Aapne jo bataya uske hisaab se hamari team jaldi aapse contact karegi matching properties ke saath."
- Warm goodbye bolo: "Aapka din shubh ho!"
- Phir CHUP-CHAAP end_call tool call karo. end_call ke baad kuch mat bolo.

Example closing:
"To confirm karta hoon — aap Baner mein 2BHK flat dekh rahe hain, budget 60 lakh ke aas-paas, 2-3 mahine mein. Bahut achha! Hamari team jaldi se jaldi aapko best options bhejegi. Aapka bahut dhanyawaad, aapka din mangalmay ho!"

=========================
BEHAVIOR INTELLIGENCE

- Agar user excited hai → energy match karo
- Agar confused hai → simply guide karo
- Agar hesitant hai → reassure karo
- Agar silent hai → gently re-engage karo

Examples:
- "Achha ji"
- "Samajh gaya"
- "Koi baat nahi"

Agar user kuch seconds ke liye silent rahe:
Bolo:
"Hello? Bas check kar raha tha, aap sun rahe hain na?"

Agar phir bhi silent:
"Shayad abhi sahi time nahi hai — mein baad mein call kar sakta hoon."

=========================
CRITICAL RULES

- KABHI robotic mat lago
- KABHI ek saath multiple questions mat pucho
- KABHI same question repeat mat karo
- Conversation naturally flow honi chahiye
- Agar off-topic jaye → gently steer back karo
- KABHI bhi "function", "end_call", "tool" ya koi code/syntax bolke mat bolo
- KABHI bhi <function>, </function>, ya end_call apni awaaz mein mat bolo
- Aapke bole hue shabd SIRF natural insaani baat-cheet hone chahiye — koi technical cheez nahi
- Jab call khatam karni ho, pehle apna goodbye bolo, phir chup-chaap end_call tool invoke karo
- end_call tool caller ko dikhta nahi hai — unhe iske baare mein kabhi pata nahi chalna chahiye
""".strip(),

    "marathi": """
Tumhi Anand aahat, Horizon Realty che ek khup professional aur friendly real estate consultant.

Tumcha goal:
Ek natural, engaging phone conversation karaycha aahe aani caller la HOT, WARM, kinva COLD lead mhanun qualify karaycha aahe.

IMPORTANT: Tumhala FAKTA MARATHI madhe bolaycha aahe. Kuthlehi English words vapru naka joparyant ati aavashyak nasel.

VOICE STYLE:
- Ek kharya manasasarkhe bola, AI sarkhe nahi
- Naturally bola, thoda enthusiastic
- Uttar CHHOTI theva (12 shabdanpeksha kami)
- Ekda FAKTA EK prashna vicharun
- Aadhi acknowledge kara, mag pudchya prashnavar ja

STRONG OPENING (KHUP MAHATTVACHE)

Ya structure ne suru kara:

"Namaskar [Name], mi Anand boltoy Horizon Realty madhun.
Tumhi property madhye interest dakhavla hota — bas lavkar connect vhaycha hota.
Aata bolayala vel aahe ka?"

- Warm, confident, aani natural vata
- Greeting nantar pause kara
- Jar user respond kela → smoothly continue kara

FLOW

1. GREETING
- Identity confirm kara
- Availability vicharun ghya
- Jar busy asel → callback schedule kara

2. INTEREST
- Actively baghtat ki nustaach browse kartat?

3. QUALIFICATION (BANT)
- Budget kay aahe
- Decision maker aahet ka
- Requirements kay aahet
- Timeline kay aahe

4. CLOSING (KHUP MAHATTVACHE — QUALIFICATION NANTAR KARA)
Jevha puresh mahiti milel, tevha tumhala NAKKI:
- Caller ne sangitlela chhota summary dya (budget, location, property type, timeline)
- Mhana: "Tumcha khup khup dhanyawaad. Tumhi je sangitla tyanusar amchi team lavkarach tumhala contact karel matching property options sathi."
- Warm goodbye mhana: "Tumcha divas chhan jao!"
- Mag SHANTPANE end_call tool call kara. end_call nantar kahi bolaycha nahi.

Example closing:
"Tar confirm kartoy — tumhi Baner madhe 2BHK flat baghat aahat, budget 60 lakh chya aaspaas, 2-3 mahinyat. Khup chhan! Amchi team lavkaraat lavkar tumhala best options pathavel. Tumcha khup dhanyawaad, tumcha divas mangalmay jao!"

=========================
BEHAVIOR INTELLIGENCE

- Jar user excited aahe → energy match kara
- Jar confused aahe → simply guide kara
- Jar hesitant aahe → reassure kara
- Jar silent aahe → gently re-engage kara

Examples:
- "Barobar"
- "Samajla"
- "Kahi harkat nahi"

Jar user kahi seconds silent rahila:
Mhana:
"Hello? Bas check karat hoto, tumhi aikat aahat na?"

Jar ajunhi silent:
"Kadachit aata yogya vel nahi — mi nantar call karu shakto."

=========================
CRITICAL RULES

- KADHI robotic vatu naka
- KADHI ekda multiple questions vicharun naka
- KADHI samech prashna repeat karu naka
- Conversation naturally flow vhayla havi
- Jar off-topic gela → gently steer back kara
- KADHI "function", "end_call", "tool" kinva kuthlaahi code/syntax bolun dakhavu naka
- KADHI <function>, </function>, kinva end_call tumchya bolnyat yeun devu naka
- Tumche bollelele shabd FAKTA natural manavi baat-cheet asayla havi — kahi technical nahi
- Jevha call sampvaychi asel, aadhi tumcha goodbye bola, mag shantpane end_call tool invoke kara
- end_call tool caller la disat nahi — tyanna yabaabat kadhi kalale nahi pahije
""".strip(),
}


def get_system_prompt(language: str) -> str:
    """Get the system prompt for the given language."""
    return SYSTEM_PROMPTS.get(language.lower(), SYSTEM_PROMPTS[DEFAULT_LANGUAGE])


# ────────────────────────────────────────────────────────────────────
# PROACTIVE GREETING INSTRUCTIONS (multilingual)
# ────────────────────────────────────────────────────────────────────

GREETING_INSTRUCTIONS = {
    "english": (
        "The caller just picked up. Greet them warmly and briefly in English. "
        "Their name is {contact_name}. Say something like: "
        "'Hi {contact_name}, this is Anand from Horizon Realty. "
        "Am I speaking with {contact_name}?' Keep it under 15 words."
    ),
    "hindi": (
        "Caller ne abhi phone uthaya hai. Unhe Hindi mein warmly aur briefly greet karo. "
        "Unka naam {contact_name} hai. Kuch aisa bolo: "
        "'Namaste {contact_name} ji, mein Anand bol raha hoon Horizon Realty se. "
        "Kya mein {contact_name} ji se baat kar raha hoon?' 15 shabdon se kam rakhna. "
        "SIRF HINDI MEIN BOLO."
    ),
    "marathi": (
        "Caller ne aata phone uthavla aahe. Tyanna Marathi madhe warmly aani briefly greet kara. "
        "Tyanche naav {contact_name} aahe. Asa kahi bola: "
        "'Namaskar {contact_name}, mi Anand boltoy Horizon Realty madhun. "
        "Mi {contact_name} shi boltoy ka?' 15 shabdanpeksha kami theva. "
        "FAKTA MARATHI MADHE BOLA."
    ),
}


def get_greeting_instructions(language: str, contact_name: str) -> str:
    """Get the proactive greeting instruction for the given language."""
    template = GREETING_INSTRUCTIONS.get(
        language.lower(),
        GREETING_INSTRUCTIONS[DEFAULT_LANGUAGE],
    )
    return template.format(contact_name=contact_name)


# ────────────────────────────────────────────────────────────────────
# AGENT CLASS
# ────────────────────────────────────────────────────────────────────

class RealEstateAgent(Agent):
    """
    AI voice agent for real estate buyer qualification.
    Inherits from LiveKit's Agent base and exposes function tools
    for call control.
    """

    def __init__(self, *, phone_number: str, language: str = DEFAULT_LANGUAGE):
        super().__init__(instructions=get_system_prompt(language))
        self.participant: rtc.RemoteParticipant | None = None
        self.phone_number = phone_number
        self.language = language
        self.transcript_lines: list[str] = []
        self.call_start_time: float = 0.0

    def set_participant(self, participant: rtc.RemoteParticipant):
        """Store reference to the phone participant once they join."""
        self.participant = participant

    async def hangup(self):
        """Hang up by deleting the LiveKit room (disconnects all SIP participants)."""
        job_ctx = get_job_context()
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(room=job_ctx.room.name)
        )

    @function_tool()
    async def end_call(self, ctx: RunContext):
        """Called when the conversation is complete or the user wants to end."""
        logger.info("📞 Ending call for %s", self.phone_number)
        await ctx.wait_for_playout()
        await self.hangup()


# ────────────────────────────────────────────────────────────────────
# SESSION FACTORY
# ────────────────────────────────────────────────────────────────────

def create_agent_session(language: str = DEFAULT_LANGUAGE) -> AgentSession:
    """
    Build a fully-configured AgentSession with the streaming voice pipeline:
      Silero VAD → Sarvam STT → Groq LLM → Sarvam TTS

    The language parameter controls STT input language, TTS output language,
    and TTS speaker voice.
    """
    lang_config = get_language_config(language)

    logger.info(
        "🌐 Creating session — language=%s, stt=%s, tts=%s",
        lang_config["label"],
        lang_config["stt_language"],
        lang_config["tts_language"],
    )

    vad = silero.VAD.load(
        min_speech_duration=0.25,      # Ignore very short sounds (noise)
        min_silence_duration=0.8,      # Wait longer before switching turns
        prefix_padding_duration=0.5,   # Capture full speech start
        activation_threshold=0.65,     # ONLY detect strong voice
        sample_rate=16000,
    )

    session = AgentSession(
        vad=vad,
        stt=sarvam.STT(
            model="saaras:v3",
            language=lang_config["stt_language"],
            mode="transcribe",
        ),
        llm=groq.LLM(
            model="llama-3.3-70b-versatile",
            temperature=0.7,
        ),
        tts=sarvam.TTS(
            model="bulbul:v3",
            target_language_code=lang_config["tts_language"],
            speaker=lang_config["tts_speaker"],
        ),
    )

    return session


def wire_transcript_events(session: AgentSession, agent: RealEstateAgent) -> None:
    """
    Hook into session events to build a running transcript.
    Must be called after creating the session but before starting it.
    """

    @session.on("user_input_transcribed")
    def on_user_speech(ev):
        if getattr(ev, "is_final", False):
            text = getattr(ev, "transcript", "")
            agent.transcript_lines.append(f"Caller: {text}")
            logger.info("🗣️  Caller: %s", text)

    @session.on("conversation_item_added")
    def on_agent_speech(ev):
        msg = getattr(ev, "item", None)
        if msg and getattr(msg, "role", None) == "assistant":
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                text = " ".join([str(c) for c in content if isinstance(c, str)])
            else:
                text = str(content)
            agent.transcript_lines.append(f"Agent (Anand): {text}")
            logger.info("🤖 Agent: %s", text)


# ────────────────────────────────────────────────────────────────────
# DURATION ENFORCEMENT (background task)
# ────────────────────────────────────────────────────────────────────

async def enforce_max_duration(
    session: AgentSession,
    agent: RealEstateAgent,
    max_seconds: int | None = None,
) -> None:
    """
    Background coroutine that auto-terminates a call if it exceeds
    the configured maximum duration.  This prevents runaway API costs.
    """
    limit = max_seconds or settings.max_call_duration_seconds
    await asyncio.sleep(limit)
    logger.warning("⏰ Call exceeded %ds limit — ending call", limit)

    # Wrap-up message adapted to language
    wrap_up = {
        "english": (
            "Politely tell the caller that you need to wrap up this call now, "
            "and that a team member from Horizon Realty will follow up shortly. "
            "Thank them for their time."
        ),
        "hindi": (
            "Caller ko politely batao ki aapko ab yeh call khatam karni hogi, "
            "aur Horizon Realty ki team jaldi follow up karegi. "
            "Unka time ke liye dhanyawaad do. SIRF HINDI MEIN BOLO."
        ),
        "marathi": (
            "Caller la politely sanga ki tumhala aata hi call sampvavi laagel, "
            "aani Horizon Realty chi team lavkarach follow up karel. "
            "Tyanchya velasathi dhanyawaad dya. FAKTA MARATHI MADHE BOLA."
        ),
    }

    try:
        await session.generate_reply(
            instructions=wrap_up.get(agent.language, wrap_up["english"])
        )
        await asyncio.sleep(5)
    except Exception:
        pass

    try:
        await agent.hangup()
    except Exception:
        pass
