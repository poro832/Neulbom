-- 보호자 개인 열쇠 (설계: 노션 「설계 — 보호자 요청 인증」).
-- 기존 서버(RDS)에 한 번 실행한다. 새 설치는 db/schema.sql에 같은 내용이 있다.
-- 원격 DB에 쓰는 일이므로 실행 전에 내용을 확인하고 사용자가 psql로 직접 돌린다.

CREATE TABLE guardian_keys (
    key_id       BIGSERIAL PRIMARY KEY,
    guardian_id  BIGINT NOT NULL REFERENCES guardians(guardian_id) ON DELETE CASCADE,
    key_prefix   TEXT NOT NULL,
    key_hash     TEXT NOT NULL UNIQUE,
    label        TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at   TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ
);
CREATE INDEX guardian_keys_guardian_idx ON guardian_keys (guardian_id);

ALTER TABLE calls ADD COLUMN requested_by_guardian_id BIGINT REFERENCES guardians(guardian_id) ON DELETE SET NULL;
