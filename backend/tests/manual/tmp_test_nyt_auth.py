import json
from app.database import SessionLocal
from app.models.auth_config import AuthConfig
from app.utils.encryption import decrypt_data

AUTH_ID = "9c0400f6-9540-4d4f-a75b-30188f63655b"

db = SessionLocal()
try:
    cfg = db.query(AuthConfig).filter(AuthConfig.id == AUTH_ID).first()
    print('cfg_found=', bool(cfg))
    print('auth_type=', cfg.auth_type.value if cfg else None)
    raw = decrypt_data(cfg.credentials) if cfg and cfg.credentials else {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    print('cred_keys=', sorted(list(raw.keys())) if isinstance(raw, dict) else type(raw))
    cookies = raw.get('cookies') if isinstance(raw, dict) else None
    if isinstance(cookies, dict):
        keys = sorted([k for k,v in cookies.items() if k and v])
        print('cookie_count=', len(keys))
        print('cookie_keys_sample=', keys[:25])
    else:
        print('cookies_missing_or_not_dict=', type(cookies).__name__)
finally:
    db.close()
