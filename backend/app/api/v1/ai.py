"""Which free AI provider is configured, and a connection test. Keys are never returned."""

import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from agents.application_agent.ai_tailor import ai_config
from app.db.enums import Actor
from app.db.models import User
from app.db.session import get_db
from app.deps import RequestCtx, owner_only, rate_limit, request_ctx
from app.services import audit
from app.services.secrets import has_secret
from integrations.llm import PROVIDERS, LLMError, chat_json

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status")
def ai_status(user: User = Depends(owner_only), db: Session = Depends(get_db)) -> dict:
    provider, model, _key, _url = ai_config(db, user.id)
    return {
        "provider": provider.key if provider else "off",
        "model": model,
        "ready": bool(provider) and (provider.secret is None or has_secret(db, user.id, provider.secret)),
        "providers": [
            {
                "key": p.key,
                "label": p.label,
                "default_model": p.default_model,
                "needs_key": p.secret is not None,
                "secret_name": p.secret,
                "key_stored": has_secret(db, user.id, p.secret) if p.secret else None,
                "privacy": p.privacy,
            }
            for p in PROVIDERS.values()
        ],
    }


@router.post("/test", dependencies=[Depends(rate_limit("ai_test", 3))])
def ai_test(
    user: User = Depends(owner_only), db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)
) -> dict:
    """A tiny request (no personal data) to check the key, the model name and the connection."""
    provider, model, key, ollama_url = ai_config(db, user.id)
    if provider is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "AI is turned off: choose a provider in Settings → AI and save")
    started = time.monotonic()
    try:
        out, _ = chat_json(
            provider, model=model, api_key=key, ollama_url=ollama_url, temperature=0,
            system='Reply with the JSON object {"ok": true} and nothing else.', user="ping",
        )  # fmt: skip
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    seconds = round(time.monotonic() - started, 1)
    ok = out.get("ok") is True
    audit.record(db, action="ai.test", actor=Actor.user, user_id=user.id,
                 after={"provider": provider.key, "model": model, "ok": ok}, request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return {"ok": ok, "provider": provider.key, "model": model, "seconds": seconds}
