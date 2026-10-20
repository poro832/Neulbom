-- 어르신 연결 코드를 고정 코드로 바꾼다: 어르신마다 하나, 만료되지 않고, 어르신 앱에서 언제든 다시 본다.
-- 옛 코드(24시간 만료, 지문만 저장)는 원문이 없어 다시 보여 줄 수 없으므로 지운다. 어르신은 앱을 열면 새 고정 코드를 받는다.
ALTER TABLE elder_link_codes ADD COLUMN IF NOT EXISTS code TEXT;
ALTER TABLE elder_link_codes ALTER COLUMN expires_at DROP NOT NULL;
DELETE FROM elder_link_codes WHERE code IS NULL;

-- 보호자가 어르신 전화번호를 고치면 새 폰이 24시간 동안 번호만으로 한 번 로그인할 수 있다. 쓰거나 만료되면 NULL이다.
ALTER TABLE elders ADD COLUMN IF NOT EXISTS phone_claim_until TIMESTAMPTZ;
