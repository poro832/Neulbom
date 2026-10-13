-- 보호자 폰 등록(푸시 알림) (설계: docs/plans/2026-10-13-push-notifications-design.md).
-- 기존 서버(RDS)에 한 번 실행한다. 새 설치는 db/schema.sql에 같은 내용이 있다.
-- 원격 DB에 쓰는 일이므로 실행 전에 내용을 확인하고 사용자가 psql로 직접 돌린다.

CREATE TABLE IF NOT EXISTS guardian_devices (
    token       TEXT PRIMARY KEY,
    guardian_id BIGINT NOT NULL REFERENCES guardians(guardian_id) ON DELETE CASCADE,
    key_hash    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS guardian_devices_guardian_idx ON guardian_devices (guardian_id);

COMMENT ON TABLE guardian_devices IS
    '푸시를 받을 보호자 폰(FCM 토큰). 로그인한 열쇠(key_hash)에 묶여, 열쇠가 폐기되면 읽을 때 걸러진다.';
