from __future__ import annotations

import json
from typing import Any

from .config import Settings
from .llm import LLMUnavailable, NvidiaChatClient
from .models import ResearchBundle, Scene, UploadMetadata, VideoPlan
from .utils import clean_text, dedupe_strings


SYSTEM_PROMPT = """You are an elite YouTube Shorts script doctor who deeply understands how the YouTube algorithm works.

YOUTUBE ALGORITHM KNOWLEDGE YOU MUST USE:
1. CLICK-THROUGH RATE (CTR): YouTube tests every video with a small audience first. If the title+thumbnail combo gets high clicks, YouTube pushes it to more people. Your title MUST create an irresistible curiosity gap.
2. AVERAGE VIEW DURATION (AVD): YouTube tracks what percentage of the video people watch. If viewers drop off early, the video dies. Your script MUST hook in the first 1.5 seconds and use pattern interrupts every 8-12 seconds.
3. REPLAY RATE: If viewers watch a Short more than once, YouTube boosts it massively. End with something that makes people want to rewatch.
4. SESSION TIME: YouTube rewards videos that keep users on the platform. End with a question or cliffhanger that makes viewers seek more content.
5. ENGAGEMENT SIGNALS: Comments, likes, shares, and saves all boost reach. Write lines that provoke opinions ("Would you use this?" "Most people get this wrong").

SCRIPT RULES:
- Scene 1 MUST be an emotional gut-punch: shock, fear, excitement, or a bold contrarian claim. Never start with "Hey guys" or "What if I told you" or "In today's world".
- Use SHORT punchy sentences. One idea per scene. Fast cuts beat slow explanations.
- Write like you're texting a smart friend, not reading a script. Use contractions, slang, rhetorical questions.
- Plant an OPEN LOOP in scene 1-2 (a question/mystery) that only resolves in the final scene. This forces watch-through.
- Every 2-3 scenes, add a PATTERN INTERRUPT moment in the visual direction (zoom cut, color shift, glitch, bass drop).
- End with a LOOPABLE question or prediction that makes the viewer rewatch or comment.
- NEVER use these dead phrases: "hidden signal", "game changer", "unlock", "delve", "in today's fast-paced world", "let's dive in", "buckle up".

TITLE RULES:
- Front-load the most emotionally charged word in the first 3 words.
- Use power words: "secretly", "just changed", "nobody noticed", "warning", "finally", "just leaked".
- Create a curiosity gap: promise a revelation without giving it away.
- Keep between 40-65 characters. Never generic like "Tech News Update".
- Use numbers when natural: "3 AI Tools", "90% of People".

CONTENT RULES:
- Only original narrative. Only factual claims grounded in supplied source notes.
- Never copy source wording. Never use third-party clips, copyrighted music, logos, celebrity likeness, or cloned voices.
- Avoid medical, financial, legal, election, disaster, or safety advice unless cautious and educational.

Return valid JSON only."""


def create_video_plan(
    settings: Settings,
    llm: NvidiaChatClient,
    bundle: ResearchBundle,
    strategy: dict[str, Any],
) -> VideoPlan:
    try:
        payload = llm.json_chat(_messages(settings, bundle, strategy), temperature=0.62, max_tokens=2400)
        plan = VideoPlan.from_dict(payload)
    except Exception:
        plan = _fallback_model_plan(settings, llm, bundle, strategy)

    if not plan.scenes:
        plan = fallback_plan(settings, bundle, strategy)
    plan.metadata.hashtags = _safe_hashtags(plan.metadata.hashtags)
    plan.metadata.tags = dedupe_strings(plan.metadata.tags)
    return plan


def _fallback_model_plan(
    settings: Settings,
    llm: NvidiaChatClient,
    bundle: ResearchBundle,
    strategy: dict[str, Any],
) -> VideoPlan:
    fallback_model = settings.nvidia_fallback_model
    if fallback_model and fallback_model != settings.nvidia_model and llm.available:
        original_model = settings.nvidia_model
        settings.nvidia_model = fallback_model
        try:
            payload = llm.json_chat(_messages(settings, bundle, strategy), temperature=0.52, max_tokens=2200)
            return VideoPlan.from_dict(payload)
        except Exception:
            pass
        finally:
            settings.nvidia_model = original_model
    return fallback_plan(settings, bundle, strategy)


def fallback_plan(settings: Settings, bundle: ResearchBundle, strategy: dict[str, Any]) -> VideoPlan:
    duration = max(30, settings.video_duration_seconds)
    scene_duration = round(duration / 7, 2)
    topic = bundle.topic
    title, scenes, tags = _fallback_story_for_topic(topic, scene_duration, strategy)
    metadata = UploadMetadata(
        title=clean_text(title, 78),
        description="",
        hashtags=["#Shorts", "#AI", "#FutureOfWork", "#Automation", "#Tech"],
        tags=[topic, *tags, *strategy.get("niches", [])],
        category_id=settings.youtube_category_id,
        privacy_status=settings.youtube_privacy_status,
        contains_synthetic_media=settings.youtube_contains_synthetic_media,
        made_for_kids=settings.youtube_made_for_kids,
    )
    return VideoPlan(
        topic=topic,
        angle=bundle.angle,
        audience="busy viewers who want the real angle fast",
        title=metadata.title,
        scenes=scenes,
        metadata=metadata,
        copyright_notes=[
            "Original script generated from factual source notes.",
            "Renderer uses generated vector-like animation, not scraped media.",
            "No copyrighted music, clips, logos, or cloned voices are required.",
        ],
        disclosure_notes=[
            "Default renderer produces stylized non-realistic animation.",
            "Enable containsSyntheticMedia if you add realistic synthetic scenes, cloned voices, or synthetic music.",
        ],
    )


def _fallback_story_for_topic(topic: str, scene_duration: float, strategy: dict[str, Any]) -> tuple[str, list[Scene], list[str]]:
    topic_clean = topic.rstrip(".")
    lower = topic_clean.lower()
    if any(word in lower for word in ("quiz", "guess", "challenge", "test")):
        title = f"Can You Guess This Tech Trend?"
        lines = [
            ("You have five seconds. Guess which tech trend people are suddenly searching for.", "Tech quiz starts now", "cold open countdown, glowing question mark, fast push-in"),
            (f"Clue one. It is connected to {topic_clean}, and the signal is coming from real online attention.", "Clue one: the trend", "holographic search spikes, digital magnifier, moving data cards"),
            ("Clue two. It is not just hype. People want to know what it changes for work, money, or daily life.", "Clue two: real impact", "split-screen lifestyle and dashboard metaphor, animated arrows"),
            ("Clue three. The winner is the person who understands the use case before everyone else turns it into noise.", "Clue three: the use case", "cinematic lock-on target over floating product cards"),
            ("Answer time. This is the kind of tech topic that turns curiosity into clicks when you explain it simply.", "Answer: watch the use case", "impact reveal, light sweep, punch zoom on answer card"),
            ("The smart move is not memorizing buzzwords. It is spotting what people are confused about first.", "Confusion becomes content", "question bubbles collapsing into one clear headline"),
            ("Would you beat your friends in a tech trend quiz tomorrow?", "Would you guess it?", "final quiz board, glowing buttons, loopable CTA"),
        ]
        return title, _scenes_from_lines(lines, scene_duration), ["tech quiz", "AI quiz", "gadgets", "technology challenge"]
    if any(word in lower for word in ("funny", "comedy", "meme", "joke", "roast")):
        title = f"The Tech Joke That Is Becoming Real"
        lines = [
            ("The funniest tech jokes always have one dangerous feature. Six months later, they become product roadmaps.", "The joke became real", "meme card transforms into premium product dashboard"),
            (f"That is why {topic_clean} is worth watching. The punchline is hiding a real behavior shift.", "Punchline to product", "comic timing snap zoom into serious data wall"),
            ("People laugh first because the idea sounds ridiculous. Then they quietly start using it.", "Laugh first. Use later.", "two-panel comedy-to-workflow transition with glitch cut"),
            ("The viral angle is simple. Show the absurd part, then reveal the practical part.", "Absurd becomes useful", "falling joke cards become clean task tiles"),
            ("That contrast keeps retention high because the viewer wants to know if the joke is actually true.", "Is it actually true?", "suspense pause, question mark pulse, bass hit"),
            ("Tech comedy works best when the laugh teaches something real.", "Make the laugh useful", "spotlight over caption, dashboard wink animation"),
            ("Would you watch a tech roast that secretly explains the future?", "Roast the future?", "final stage light, glowing comment bubble CTA"),
        ]
        return title, _scenes_from_lines(lines, scene_duration), ["tech comedy", "technology memes", "creator economy", "AI tools"]
    if any(word in lower for word in ("gadget", "phone", "iphone", "android", "laptop", "device", "hardware")):
        title = f"The Gadget Trend People Are Missing"
        lines = [
            (f"{topic_clean} sounds like another gadget headline. But the interesting part is what users are comparing.", "Not just a gadget", "hero product silhouette, spec cards orbiting in darkness"),
            ("Price, battery, camera, speed. Those are obvious. The real signal is which problem people hope it solves.", "What problem changes?", "macro UI shot, comparison grid, animated checkmarks"),
            ("A strong tech video should show the tradeoff fast, not drown the viewer in specs.", "Specs are not the story", "spec sheet shatters into three readable tradeoff cards"),
            ("If it saves time, creates status, or removes friction, the trend has legs.", "Time. Status. Friction.", "three glowing pillars, dolly push, light streaks"),
            ("If it is only a tiny upgrade, the best angle is a quiz, a comparison, or a buyer warning.", "Choose the angle", "branching decision tree with quiz and warning paths"),
            ("That is how a gadget launch becomes a short people actually finish.", "Make launches watchable", "fast montage of hands, screens, and headline pulses"),
            ("Would you buy it, wait, or skip it completely?", "Buy, wait, or skip?", "final decision buttons, loopable CTA"),
        ]
        return title, _scenes_from_lines(lines, scene_duration), ["gadgets", "consumer tech", "tech news", "buying guide"]
    if any(word in lower for word in ("cyber", "security", "privacy", "hack", "scam")):
        title = f"The Security Warning Behind This Tech Trend"
        lines = [
            (f"{topic_clean} is not just a headline. It is a reminder that every new tool creates a new door.", "Every tool opens a door", "dark vault corridor, red access line, slow push-in"),
            ("Most people ask what the tool can do. Security teams ask what it can touch.", "What can it touch?", "permission map, glowing key, warning pulse"),
            ("That is the difference between useful automation and expensive chaos.", "Useful or chaotic?", "dashboard splits clean green versus red glitch"),
            ("The safe version has narrow access, logs, approvals, and a human who can stop it.", "Control beats chaos", "approval gate, audit log, shield animation"),
            ("The risky version gives powerful software a blank check and hopes nothing goes wrong.", "No blank checks", "digital check burns into firewall warning"),
            ("This is why privacy and security stories spread. They turn invisible risk into something viewers can feel.", "Make risk visible", "invisible lines become red laser grid"),
            ("Would you give an AI tool the keys without a log?", "Would you give keys?", "final lock and key CTA, bass hit"),
        ]
        return title, _scenes_from_lines(lines, scene_duration), ["cybersecurity", "privacy", "AI safety", "tech news"]
    title = f"Why {clean_text(topic_clean, 58)} Is Trending"
    lines = [
        (f"{topic_clean} is getting attention because it feels small at first, then suddenly changes what people expect from technology.", "Small signal. Big shift.", "trend spark grows into cinematic data wave"),
        ("The first layer is curiosity. People want a simple explanation before they trust the hype.", "Curiosity comes first", "question cards fly toward one clean answer"),
        ("The second layer is usefulness. Does it save time, create leverage, or make an old workflow feel outdated?", "Does it change behavior?", "old workflow dissolves into faster timeline"),
        ("The third layer is risk. Every powerful tool creates a new mistake people need to avoid.", "Power creates risk", "permission gate, red warning flash, shallow depth"),
        ("That is the story. Not the buzzword, but the behavior shift behind it.", "Find the behavior shift", "camera orbit around central hologram"),
        ("Explain that clearly, and the trend stops feeling random.", "Make the trend clear", "messy data lines snap into one bright route"),
        ("Would you use it, ignore it, or wait for version two?", "Use, skip, or wait?", "final three-choice CTA with glowing buttons"),
    ]
    return title, _scenes_from_lines(lines, scene_duration), ["tech news", "technology trend", "AI tools", "future of work"]


def _scenes_from_lines(lines: list[tuple[str, str, str]], scene_duration: float) -> list[Scene]:
    return [
        Scene(
            narration=narration,
            onscreen_text=onscreen_text,
            visual_style=visual_style,
            duration_seconds=scene_duration,
        )
        for narration, onscreen_text, visual_style in lines
    ]


def _messages(settings: Settings, bundle: ResearchBundle, strategy: dict[str, Any]) -> list[dict[str, str]]:
    growth = strategy.get("growth_strategy", {})
    source_notes = {
        "topic": bundle.topic,
        "angle": bundle.angle,
        "sources": [
            {
                "title": source.title,
                "source": source.source,
                "url": source.url,
                "excerpt": clean_text(source.excerpt, 420),
            }
            for source in bundle.sources[:4]
        ],
        "notes": bundle.notes,
    }
    source_notes_text = json.dumps(source_notes, ensure_ascii=False, indent=2)
    prompt = f"""
Create a VIRAL YouTube Shorts video plan for this trend. Your goal is to maximize CTR, watch-through rate, and engagement signals so the YouTube algorithm pushes this video to millions.

Target duration: {settings.video_duration_seconds} seconds.
Video size: {settings.video_width}x{settings.video_height}.
Channel niches: {", ".join(strategy.get("niches", []))}.

ALGORITHM OPTIMIZATION RULES:
{json.dumps(growth.get("retention_rules", []), ensure_ascii=False)}

TITLE OPTIMIZATION:
{json.dumps(growth.get("title_rules", []), ensure_ascii=False)}

Source notes:
{source_notes_text}

Return JSON with this exact structure:
{{
  "topic": "...",
  "angle": "a sharp, specific angle that makes this feel urgent and new",
  "audience": "specific viewer persona who would stop scrolling for this",
  "candidate_titles": [
    "title option 1 (curiosity gap)",
    "title option 2 (fear/warning)",
    "title option 3 (contrarian)",
    "title option 4 (insider secret)",
    "title option 5 (urgent timeline)"
  ],
  "title": "the absolute best title from the 5 options above, optimized for max CTR",
  "scenes": [
    {{
      "narration": "punchy spoken line — one idea, emotional, conversational",
      "onscreen_text": "2-5 word text overlay that reinforces the hook",
      "visual_style": "specific cinematic animation direction with VFX language",
      "duration_seconds": 5.5
    }}
  ],
  "metadata": {{
    "title": "same winning title from above",
    "description": "",
    "hashtags": ["#Shorts", "#Tech"],
    "tags": ["exact topic keyword", "long-tail search phrase viewers type", "broad category"],
    "category_id": "{settings.youtube_category_id}",
    "privacy_status": "{settings.youtube_privacy_status}",
    "contains_synthetic_media": false,
    "made_for_kids": false
  }},
  "copyright_notes": ["..."],
  "disclosure_notes": ["..."]
}}

SCENE STRUCTURE (7-9 scenes, this structure is NON-NEGOTIABLE):
- Scene 1 (THE HOOK): Emotional gut-punch. Bold claim, shocking stat, or contrarian take. This determines if YouTube shows the video to anyone. Make it impossible to scroll past.
- Scene 2 (OPEN LOOP): Plant a mystery or unanswered question. "But here's what nobody is talking about..." This forces the viewer to keep watching.
- Scene 3-4 (RISING TENSION): Escalate stakes. Each scene more intense than the last. Use pattern interrupt visuals (glitch, zoom, color shift).
- Scene 5-6 (THE MECHANISM): Reveal the "how" or "why". This is the value payload. One clear insight per scene.
- Scene 7 (PAYOFF): Resolve the open loop from scene 2. Deliver the promised revelation.
- Scene 8-9 (LOOPABLE CTA): End with a provocative question, prediction, or challenge that makes viewers comment, rewatch, or share. "Would you trust an AI with your job?" "Most people get this wrong."

NARRATION RULES:
- Sound like a sharp creator talking to ONE person, not a crowd.
- Use contractions (it's, don't, you're). Use rhetorical questions. Use dramatic pauses via short sentences.
- Each line must be under 18 words. Shorter = faster pacing = higher retention.
- NEVER start with "Hey guys", "What if I told you", "In today's world", or any generic opener.

VISUAL RULES:
- Each scene must describe a DIFFERENT cinematic animation idea.
- Use VFX language: camera push, parallax, light trails, particles, glass panels, shockwave, glitch, speed ramp, depth blur, volumetric glow, lens flare, whip pan.
- Do not request real footage, scraped images, brand logos, celebrity faces, copyrighted music, or cloned voices.

TAGS/SEO RULES:
- First tag must be the exact topic keyword.
- Include 3-5 long-tail search phrases real viewers would type into YouTube.
- Include broad category tags (AI, tech, gadgets).
- Total tags under 450 characters.

POLICY:
- Do not fabricate quotes or attribute actions to people unless source notes explicitly support it.
- No medical, investment, election, or disaster advice.
- Metadata must be truthful. No misleading hashtags.
"""
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]


def _safe_hashtags(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        tag = "".join(ch for ch in value.replace("#", "") if ch.isalnum() or ch == "_")
        if tag:
            cleaned.append(f"#{tag}")
    return dedupe_strings(cleaned)
