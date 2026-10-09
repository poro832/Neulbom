-- 앱 화면을 실제 데이터로 (설계: docs/plans/2026-10-09-app-real-data-design.md).
-- 기존 서버(RDS)에 한 번 실행한다. 새 설치는 db/schema.sql에 같은 내용이 있다.
-- 원격 DB에 쓰는 일이므로 실행 전에 내용을 확인하고 사용자가 psql로 직접 돌린다.

-- 어르신 연결 코드. 코드는 지문만 저장한다.
CREATE TABLE elder_pairings (
    pairing_id      BIGSERIAL PRIMARY KEY,
    elder_id        BIGINT NOT NULL REFERENCES elders(elder_id) ON DELETE CASCADE,
    code_hash       TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    failed_attempts INT NOT NULL DEFAULT 0,
    used_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX elder_pairings_elder_idx ON elder_pairings (elder_id, pairing_id DESC);

-- 어르신 폰 전용 열쇠. 지문만 저장한다(app/api/elder_auth.py).
CREATE TABLE elder_keys (
    key_id       BIGSERIAL PRIMARY KEY,
    elder_id     BIGINT NOT NULL REFERENCES elders(elder_id) ON DELETE CASCADE,
    key_prefix   TEXT NOT NULL,
    key_hash     TEXT NOT NULL UNIQUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at   TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ
);
CREATE INDEX elder_keys_elder_idx ON elder_keys (elder_id);

-- 어르신이 직접 추가한 비상 연락처.
CREATE TABLE contacts (
    contact_id   BIGSERIAL PRIMARY KEY,
    elder_id     BIGINT NOT NULL REFERENCES elders(elder_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    relation     TEXT NOT NULL DEFAULT '',
    phone_number TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX contacts_elder_idx ON contacts (elder_id, contact_id);

-- 웹훅이 다시 와도 한 통화에 같은 종류 알림이 둘 생기지 않게 한다.
CREATE UNIQUE INDEX alerts_call_type_idx ON alerts (call_id, alert_type) WHERE call_id IS NOT NULL;
