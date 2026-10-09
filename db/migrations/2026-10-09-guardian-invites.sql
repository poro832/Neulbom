-- 보호자 코드로 어르신 가입 (설계: docs/plans/2026-10-09-guardian-invite-signup-design.md).
-- 기존 서버(RDS)에 한 번 실행한다. 새 설치는 db/schema.sql에 같은 내용이 있다.
-- 원격 DB에 쓰는 일이므로 실행 전에 내용을 확인하고 사용자가 psql로 직접 돌린다.

-- 어르신이 가입 화면에서 동의에 체크한 시각. 보호자 승인(consent_at) 전에는 이것만 채워진다.
ALTER TABLE elders ADD COLUMN agreed_at TIMESTAMPTZ;

-- 보호자 개인 코드. 지문만 저장한다. 보호자당 활성(revoked_at IS NULL) 코드는 하나뿐이다.
CREATE TABLE guardian_invites (
    invite_id   BIGSERIAL PRIMARY KEY,
    guardian_id BIGINT NOT NULL REFERENCES guardians(guardian_id) ON DELETE CASCADE,
    code_hash   TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ
);
CREATE UNIQUE INDEX guardian_invites_active_idx ON guardian_invites (guardian_id) WHERE revoked_at IS NULL;
