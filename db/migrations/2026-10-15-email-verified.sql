-- 보호자 이메일 인증. 비어 있으면 이메일 소유를 아직 증명하지 못한 보호자(앱에서 가입).
-- 기본값 now()라 기존 보호자·운영 도구·시드가 만든 보호자는 인증된 것으로 시작한다.
ALTER TABLE guardians ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ DEFAULT now();
