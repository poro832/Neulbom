-- 보호자 운영자 활성화 (설계: docs/plans/2026-10-13-guardian-accounts-design.md, 활성화 덧붙임).
-- 기존 서버(RDS)에 한 번 실행한다. 새 설치는 db/schema.sql에 같은 내용이 있다.
-- 원격 DB에 쓰는 일이므로 실행 전에 내용을 확인하고 사용자가 psql로 직접 돌린다.
--
-- 기본값 now()는 ADD COLUMN 시점에 지금 있는 보호자 행에도 채워진다 — 기존 보호자는 열린 상태가 된다.
-- 앱에서 가입한 보호자만 코드가 activated_at = NULL로 넣어 확인 대기가 된다.

ALTER TABLE guardians ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ DEFAULT now();
