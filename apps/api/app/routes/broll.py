from __future__ import annotations

from fastapi import APIRouter

from ai.analysis import MomentAnalyzer
from ai.longcat import LongCatClient
from ai.prompts import render_prompt
from fastapi import Depends
from app.deps import verify_worker_token
from app.schemas import BrollRequest

router = APIRouter(prefix="/v1", tags=["broll"], dependencies=[Depends(verify_worker_token)])


@router.post("/broll/prompt")
async def broll_prompt(body: BrollRequest) -> dict:
    """Turn a clip segment into a LongCat text-to-video prompt (deterministic template)."""
    _, system, user = render_prompt(
        "broll_prompt",
        {"context": body.context, "startSec": body.startSec, "endSec": body.endSec},
    )
    return {"system": system, "user": user}


@router.post("/broll/generate")
async def broll_generate(body: BrollRequest) -> dict:
    """Generate AI B-roll via the LongCat GPU worker. Returns null footage when unavailable."""
    client = LongCatClient()
    if not client.available:
        return {"available": False, "footage": None,
                "reason": "The LongCat GPU worker is not enabled for this instance."}
    analyzer = MomentAnalyzer()
    prompt = f"Cinematic vertical B-roll supporting: {body.context}"
    footage = client.generate(
        __import__("ai.longcat", fromlist=["BrollInsert"]).BrollInsert(
            prompt=prompt,
            negative_prompt="text, watermark, distorted faces, logos",
            seconds=max(1.0, min(8.0, body.endSec - body.startSec)),
        )
    )
    return {"available": True, "footage": footage}
