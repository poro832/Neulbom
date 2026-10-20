-- 한 어르신을 여러 보호자가 함께 본다. elders.guardian_id는 "대표 보호자"로 남긴다.
-- 서버 코드를 올리기 전에 먼저 실행한다(코드가 이 표를 읽는다). 여러 번 실행해도 안전하다.

CREATE TABLE IF NOT EXISTS elder_guardians (
    elder_id    BIGINT NOT NULL REFERENCES elders(elder_id) ON DELETE CASCADE,
    guardian_id BIGINT NOT NULL REFERENCES guardians(guardian_id) ON DELETE CASCADE,
    linked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (elder_id, guardian_id)
);

CREATE INDEX IF NOT EXISTS elder_guardians_guardian_idx ON elder_guardians (guardian_id);

-- 알림은 보호자마다 한 건씩 남긴다(같은 통화·같은 종류라도 보호자가 다르면 따로).
DROP INDEX IF EXISTS alerts_call_type_idx;
CREATE UNIQUE INDEX IF NOT EXISTS alerts_call_type_idx
    ON alerts (call_id, alert_type, guardian_id) WHERE call_id IS NOT NULL;

-- 지금 보호자가 있는 어르신을 모두 옮긴다.
INSERT INTO elder_guardians (elder_id, guardian_id)
SELECT elder_id, guardian_id FROM elders WHERE guardian_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- 대표 보호자 칸에 누군가 적히면 그 사람도 보호자 목록에 들어간다(옛 코드·운영 도구가 이 칸만 써도 어긋나지 않게).
CREATE OR REPLACE FUNCTION elder_primary_guardian_sync() RETURNS trigger AS $$
BEGIN
    INSERT INTO elder_guardians (elder_id, guardian_id)
    VALUES (NEW.elder_id, NEW.guardian_id)
    ON CONFLICT DO NOTHING;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS elders_primary_guardian_sync ON elders;
CREATE TRIGGER elders_primary_guardian_sync
AFTER INSERT OR UPDATE OF guardian_id ON elders
FOR EACH ROW WHEN (NEW.guardian_id IS NOT NULL)
EXECUTE FUNCTION elder_primary_guardian_sync();
