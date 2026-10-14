-- 어르신 먼저 가입: 가입 시점에는 담당 보호자가 없다. 보호자가 연결 코드를 확인하면 채워진다.
-- 보호자 없는 어르신은 consent_at이 NULL이라 전화 대상(elders_due_idx)에서 빠진다.
ALTER TABLE elders ALTER COLUMN guardian_id DROP NOT NULL;

-- 어르신 연결 코드. 코드는 지문만 저장한다. 어르신당 하나이고 재발급하면 덮어쓴다.
CREATE TABLE IF NOT EXISTS elder_link_codes (
    elder_id   BIGINT PRIMARY KEY REFERENCES elders(elder_id) ON DELETE CASCADE,
    code_hash  TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
